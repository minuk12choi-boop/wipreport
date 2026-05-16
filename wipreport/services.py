from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
import logging

from django.conf import settings
from django.db import connection
from django.db.models import Model, QuerySet

from .models import (
    WipMoveGroup,
    WipRefExclusionTypeRule,
    WipRefHotLotRule,
    WipRefModuleRule,
    WipRefProductRule,
    WipReportLotPath,
)
from .ref_services import (
    area_from_eqp,
    classify_exclusion_type,
    classify_hot_lot,
    classify_module,
    classify_product,
    parse_issue_eqp,
    parse_prevent,
)

logger = logging.getLogger(__name__)

WIP_FIELDS = ["lot_id", "status", "cur_qty", "lot_type", "proc_id", "layer_id", "step_seq", "issue_eqp", "prevent", "exclusion_type", "grade", "lot_inform"]


def get_latest_loaded_at():
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT MAX(`loaded_at`) FROM `wip_report_lotpath`")
            row = cursor.fetchone()
        return row[0] if row and row[0] else '-'
    except Exception as exc:
        logger.exception('[latest_loaded_at 오류] %s: %s', exc.__class__.__name__, exc)
        return '-'


def _to_num(v):
    try:
        return float(v or 0)
    except Exception:
        return 0.0


def make_json_safe(value):
    if isinstance(value, dict):
        return {str(k): make_json_safe(v) for k, v in value.items()}
    if isinstance(value, QuerySet):
        return [make_json_safe(v) for v in value]
    if isinstance(value, (list, tuple)):
        return [make_json_safe(v) for v in value]
    if isinstance(value, set):
        return [make_json_safe(v) for v in sorted(value, key=lambda x: str(x))]
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Model):
        return str(value)
    if hasattr(value, 'item'):
        try:
            return value.item()
        except Exception:
            return str(value)
    if hasattr(value, 'tolist'):
        try:
            return value.tolist()
        except Exception:
            return str(value)
    return value


def build_summary(params):
    try:
        lot_types = params.getlist('lot_type') if hasattr(params, 'getlist') else (params.get('lot_type') or ['PP'])
        lot_types = lot_types or ['PP']
        page_size = int((params.get('page_size') if hasattr(params, 'get') else None) or 100)
        page_size = min(max(page_size, 1), 300)

        product_rules = list(WipRefProductRule.objects.filter(is_active=True).order_by('sort_no', 'id'))
        module_rules = list(WipRefModuleRule.objects.filter(is_active=True).order_by('sort_no', 'id'))
        ex_rules = list(WipRefExclusionTypeRule.objects.filter(is_active=True).order_by('sort_no', 'id'))
        hot_rules = list(WipRefHotLotRule.objects.filter(is_active=True).order_by('sort_no', 'id'))

        rows = list(WipReportLotPath.objects.filter(lot_type__in=lot_types).values(*WIP_FIELDS)[:2000])

        dedup_lot = {}
        for r in rows:
            lot = (r.get('lot_id') or '').strip()
            if lot and lot not in dedup_lot:
                dedup_lot[lot] = r
        uniq_rows = list(dedup_lot.values())

        lot_balance = defaultdict(lambda: defaultdict(float))
        layer_seen = set()
        for r in rows:
            key = ((r.get('lot_id') or ''), (r.get('layer_id') or ''), (r.get('status') or ''))
            if key in layer_seen:
                continue
            layer_seen.add(key)
            lot_balance[r.get('layer_id') or '-'][r.get('status') or '-'] += _to_num(r.get('cur_qty'))

        issue_acc = defaultdict(lambda: {'qty': 0.0, 'lots': set(), 'category': '', 'issue': '', 'status': '', 'need_check': ''})
        for r in uniq_rows:
            qty = _to_num(r.get('cur_qty'))
            lot = r.get('lot_id') or ''
            for i in parse_issue_eqp(r.get('issue_eqp') or ''):
                k = ('설비이슈', i['eqp'], i['status'])
                a = issue_acc[k]
                a.update({'category': '설비이슈', 'issue': i['eqp'], 'status': f"{i['status']}({i['days']}일↑)", 'need_check': area_from_eqp(i['eqp'])})
                a['qty'] += qty
                a['lots'].add(lot)
            for p in parse_prevent(r.get('prevent') or ''):
                k = ('TIP', p['eqp'], 'PREVENT')
                a = issue_acc[k]
                a.update({'category': 'TIP', 'issue': p['eqp'], 'status': f"PREVENT({p['days']}일↑)", 'need_check': area_from_eqp(p['eqp'])})
                a['qty'] += qty
                a['lots'].add(lot)
            ex_type = classify_exclusion_type(r.get('exclusion_type') or '', ex_rules)
            if ex_type:
                k = ('EXCLUSION', ex_type, '미정')
                a = issue_acc[k]
                a.update({'category': 'EXCLUSION', 'issue': ex_type, 'status': '미정', 'need_check': '미정'})
                a['qty'] += qty
                a['lots'].add(lot)

        issue_rows = [{**v, 'qty_text': f"{int(v['qty'])}매({len(v['lots'])}Lot)"} for v in issue_acc.values()]
        issue_rows.sort(key=lambda x: x['qty'], reverse=True)

        wip_rows = []
        for r in uniq_rows[:page_size]:
            item = {k: r.get(k) for k in WIP_FIELDS if k not in {'issue_eqp', 'prevent', 'loaded_at', 'loaded_id'}}
            item['product'] = classify_product(r.get('lot_id'), product_rules)
            item['module'] = classify_module(item['product'], r.get('layer_id'), r.get('step_seq'), module_rules)
            item['hot_type'] = classify_hot_lot(r.get('grade'), r.get('lot_inform'), hot_rules)
            wip_rows.append(item)

        move_rows = list(WipMoveGroup.objects.values('report_date', 'move').order_by('-report_date')[:90])
        labels = [m['report_date'] for m in reversed(move_rows)]
        moves = [_to_num(m['move']) for m in reversed(move_rows)]

        out = {
            'ok': True,
            'latest_loaded_at': get_latest_loaded_at(),
            'message': '',
            'filters': {
                'lot_type': sorted({x['lot_type'] for x in rows if x.get('lot_type')}) or ['PP'],
                'product': sorted({classify_product(x.get('lot_id'), product_rules) for x in rows if classify_product(x.get('lot_id'), product_rules)}),
                'proc_id': sorted({x['proc_id'] for x in rows if x.get('proc_id')}),
                'issue_category': ['설비이슈', 'TIP', 'EXCLUSION'],
                'need_check': ['PHOTO', 'METRO', 'METAL', 'CMP', 'CLN', 'CVD', 'IMP', 'DIFF', '미정'],
            },
            'summary_text': [f"총 LOT: {len(uniq_rows)}", f"총 재공수량: {int(sum(_to_num(r.get('cur_qty')) for r in uniq_rows))}매", f"LOT TYPE: {', '.join(lot_types)}"],
            'lot_balance': {'labels': [], 'datasets': [], 'by_layer_status': {k: dict(v) for k, v in lot_balance.items()}},
            'index_chart': {'labels': labels, 'datasets': [{'label': 'MOVE', 'data': moves}]},
            'issue_rows': issue_rows[:200],
            'wip_rows': wip_rows,
            'pagination': {'page': 1, 'page_size': page_size, 'total': len(uniq_rows)},
        }
        return make_json_safe(out)
    except Exception as exc:
        logger.exception('[summary-data 오류] %s: %s', exc.__class__.__name__, exc)
        out = {
            'ok': False,
            'message': 'Summary 데이터 조회 중 오류가 발생했습니다.',
            'latest_loaded_at': get_latest_loaded_at(),
            'filters': {'lot_type': [], 'product': [], 'proc_id': [], 'issue_category': [], 'need_check': []},
            'summary_text': [],
            'lot_balance': {'labels': [], 'datasets': []},
            'index_chart': {'labels': [], 'datasets': []},
            'issue_rows': [],
            'wip_rows': [],
            'pagination': {'page': 1, 'page_size': 100, 'total': 0},
        }
        if settings.DEBUG:
            out['error_detail'] = f'{exc.__class__.__name__}: {exc}'
        return make_json_safe(out)
