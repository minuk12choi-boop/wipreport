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
STATUS_ORDER = ["HOLD", "RUN", "WAIT", "WAIT(진행불가)"]
STATUS_COLOR = {"HOLD": "#d9534f", "RUN": "#337ab7", "WAIT": "#3c9d3c", "WAIT(진행불가)": "#e0ad00"}

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
    return value

def _build_summary_sections(uniq_rows):
    bn_acc = defaultdict(lambda: {"qty": 0.0, "lots": set(), "wait": 0.0, "hold": 0.0, "blocked": 0.0})
    eqp_acc = defaultdict(lambda: {"qty": 0.0, "lots": set(), "days": 0.0, "status": ""})
    tip_acc = defaultdict(lambda: {"qty": 0.0, "lots": set(), "days": 0.0})
    ex_acc = defaultdict(lambda: {"qty": 0.0, "lots": set(), "reasons": defaultdict(int)})

    for r in uniq_rows:
        qty = _to_num(r.get("cur_qty"))
        lot = r.get("lot_id") or ""
        status = r.get("status") or ""
        layer = r.get("layer_id") or "-"
        step = str(r.get("step_seq") or "-")
        key = f"{layer} / STEP {step}"
        if status in ["WAIT", "HOLD", "WAIT(진행불가)"]:
            bn_acc[key]["qty"] += qty
            bn_acc[key]["lots"].add(lot)
            if status == "WAIT": bn_acc[key]["wait"] += qty
            if status == "HOLD": bn_acc[key]["hold"] += qty
            if status == "WAIT(진행불가)": bn_acc[key]["blocked"] += qty

        for i in parse_issue_eqp(r.get("issue_eqp") or ""):
            e = i.get("eqp") or "-"
            eqp_acc[e]["qty"] += qty; eqp_acc[e]["lots"].add(lot)
            eqp_acc[e]["days"] = max(eqp_acc[e]["days"], _to_num(i.get("days")))
            eqp_acc[e]["status"] = i.get("status") or "미정"
        for p in parse_prevent(r.get("prevent") or ""):
            e = p.get("eqp") or "-"
            tip_acc[e]["qty"] += qty; tip_acc[e]["lots"].add(lot)
            tip_acc[e]["days"] = max(tip_acc[e]["days"], _to_num(p.get("days")))
        ex = (r.get("exclusion_type") or "").strip()
        if ex:
            ex_acc[key]["qty"] += qty; ex_acc[key]["lots"].add(lot)
            reason = classify_exclusion_type(ex, []) or ex.split(",")[0][:20]
            ex_acc[key]["reasons"][reason] += 1

    def top_lines(acc, fn):
        items = sorted(acc.items(), key=lambda kv: kv[1].get("qty", 0), reverse=True)[:5]
        return [fn(k, v) for k, v in items] or ["해당 이슈 없음"]

    return [
        {"title": "[B/N] 병목 후보 Top 5", "lines": top_lines(bn_acc, lambda k,v: f"{k}: {int(v['qty'])}매({len(v['lots'])}Lot), WAIT {int(v['wait'])}매, HOLD {int(v['hold'])}매, WAIT(진행불가) {int(v['blocked'])}매")},
        {"title": "[설비이슈] 설비 이슈 Top 5", "lines": top_lines(eqp_acc, lambda k,v: f"{k}: {v['status']}({v['days']:.1f}일↑), {int(v['qty'])}매({len(v['lots'])}Lot)")},
        {"title": "[TIP] Prevent Top 5", "lines": top_lines(tip_acc, lambda k,v: f"{k}: PREVENT({v['days']:.1f}일↑), {int(v['qty'])}매({len(v['lots'])}Lot)")},
        {"title": "[EXCLUSION] HOLD/FTP/예약제외 Top 5", "lines": top_lines(ex_acc, lambda k,v: f"{k}: 사유 {sum(v['reasons'].values())}건, {int(v['qty'])}매({len(v['lots'])}Lot)")},
    ]

def build_summary(params):
    try:
        lot_types = params.getlist('lot_type') if hasattr(params, 'getlist') else (params.get('lot_type') or ['PP'])
        lot_types = lot_types or ['PP']
        page_size = min(max(int((params.get('page_size') if hasattr(params, 'get') else None) or 100), 1), 300)
        product_rules = list(WipRefProductRule.objects.filter(is_active=True).order_by('sort_no', 'id'))
        module_rules = list(WipRefModuleRule.objects.filter(is_active=True).order_by('sort_no', 'id'))
        ex_rules = list(WipRefExclusionTypeRule.objects.filter(is_active=True).order_by('sort_no', 'id'))
        hot_rules = list(WipRefHotLotRule.objects.filter(is_active=True).order_by('sort_no', 'id'))

        rows = list(WipReportLotPath.objects.filter(lot_type__in=lot_types).values(*WIP_FIELDS)[:2000])
        dedup = {}
        for r in rows:
            lot = (r.get('lot_id') or '').strip()
            if lot and lot not in dedup: dedup[lot] = r
        uniq_rows = list(dedup.values())

        by_layer_status = defaultdict(lambda: defaultdict(float))
        module_labels = {}
        for r in rows:
            layer = str(r.get('layer_id') or '-')
            status = r.get('status') or '-'
            by_layer_status[layer][status] += _to_num(r.get('cur_qty'))
            module_labels[layer] = classify_module(classify_product(r.get('lot_id'), product_rules), r.get('layer_id'), r.get('step_seq'), module_rules)
        labels = sorted(by_layer_status.keys(), key=lambda x: (len(x), x))
        lot_balance = {
            "labels": labels,
            "datasets": [{"label": s, "data": [int(by_layer_status[l].get(s, 0)) for l in labels], "backgroundColor": STATUS_COLOR.get(s, "#999")} for s in STATUS_ORDER],
            "module_labels": module_labels,
            "by_layer_status": {k: dict(v) for k,v in by_layer_status.items()},
        }

        issue_acc = defaultdict(lambda: {'qty': 0.0, 'lots': set(), 'category': '', 'issue': '', 'status': '', 'need_check': ''})
        for r in uniq_rows:
            qty = _to_num(r.get('cur_qty')); lot = r.get('lot_id') or ''
            for i in parse_issue_eqp(r.get('issue_eqp') or ''):
                k = ('설비이슈', i['eqp'], i['status'])
                a = issue_acc[k]; a.update({'category': '설비이슈', 'issue': i['eqp'], 'status': f"{i['status']}({i['days']}일↑)", 'need_check': area_from_eqp(i['eqp'])}); a['qty'] += qty; a['lots'].add(lot)
            for p in parse_prevent(r.get('prevent') or ''):
                k = ('TIP', p['eqp'], 'PREVENT')
                a = issue_acc[k]; a.update({'category': 'TIP', 'issue': p['eqp'], 'status': f"PREVENT({p['days']}일↑)", 'need_check': area_from_eqp(p['eqp'])}); a['qty'] += qty; a['lots'].add(lot)
            ex_type = classify_exclusion_type(r.get('exclusion_type') or '', ex_rules)
            if ex_type:
                issue = f"{r.get('layer_id') or '-'} / STEP {r.get('step_seq') or '-'}"
                k = ('EXCLUSION', issue, ex_type)
                a = issue_acc[k]; a.update({'category': 'EXCLUSION', 'issue': issue, 'status': ex_type, 'need_check': '미정'}); a['qty'] += qty; a['lots'].add(lot)
        issue_rows = [{**v, 'qty_text': f"{int(v['qty'])}매({len(v['lots'])}Lot)"} for v in issue_acc.values()]
        issue_rows.sort(key=lambda x: x['qty'], reverse=True)

        wip_rows = []
        for r in uniq_rows[:page_size]:
            item = {k: r.get(k) for k in WIP_FIELDS if k not in {'issue_eqp', 'prevent'}}
            item['product'] = classify_product(r.get('lot_id'), product_rules)
            item['module'] = classify_module(item['product'], r.get('layer_id'), r.get('step_seq'), module_rules)
            item['hot_type'] = classify_hot_lot(r.get('grade'), r.get('lot_inform'), hot_rules)
            wip_rows.append(item)

        move_rows = list(WipMoveGroup.objects.values('report_date', 'move').order_by('-report_date')[:60])
        move_rows = list(reversed(move_rows))
        idx_labels = [str(m['report_date']) for m in move_rows]
        move_data = [_to_num(m['move']) for m in move_rows]
        total_qty = sum(_to_num(r.get('cur_qty')) for r in uniq_rows) or 1
        hold_qty = sum(_to_num(r.get('cur_qty')) for r in uniq_rows if (r.get('status') or '') == 'HOLD')
        blocked_qty = sum(_to_num(r.get('cur_qty')) for r in uniq_rows if (r.get('status') or '') == 'WAIT(진행불가)')
        wait_qty = sum(_to_num(r.get('cur_qty')) for r in uniq_rows if (r.get('status') or '') == 'WAIT')
        idx_len = len(idx_labels)
        index_chart = {"labels": idx_labels, "datasets": [
            {"type": "bar", "label": "move", "data": move_data, "yAxisID": "y"},
            {"type": "line", "label": "w/t", "data": [round(wait_qty / total_qty * 100, 2)] * idx_len, "yAxisID": "y1", "spanGaps": False},
            {"type": "line", "label": "hold율[%]", "data": [round(hold_qty / total_qty * 100, 2)] * idx_len, "yAxisID": "y1", "spanGaps": False},
            {"type": "line", "label": "hold+WAIT진행불가율[%]", "data": [round((hold_qty + blocked_qty) / total_qty * 100, 2)] * idx_len, "yAxisID": "y1", "spanGaps": False},
        ]}

        out = {'ok': True, 'latest_loaded_at': get_latest_loaded_at(), 'message': '',
            'filters': {'lot_type': sorted({x['lot_type'] for x in rows if x.get('lot_type')}) or ['PP'],
                        'product': sorted({classify_product(x.get('lot_id'), product_rules) for x in rows if classify_product(x.get('lot_id'), product_rules)}),
                        'proc_id': sorted({x['proc_id'] for x in rows if x.get('proc_id')}),
                        'issue_category': ['설비이슈', 'TIP', 'EXCLUSION'],
                        'need_check': ['PHOTO', 'METRO', 'METAL', 'CMP', 'CLN', 'CVD', 'IMP', 'DIFF', '미정']},
            'summary_sections': _build_summary_sections(uniq_rows),
            'lot_balance': lot_balance,
            'index_chart': index_chart,
            'issue_rows': issue_rows[:200],
            'wip_rows': wip_rows,
            'pagination': {'page': 1, 'page_size': page_size, 'total': len(uniq_rows)}}
        return make_json_safe(out)
    except Exception as exc:
        logger.exception('[summary-data 오류] %s: %s', exc.__class__.__name__, exc)
        out = {'ok': False, 'message': 'Summary 데이터 조회 중 오류가 발생했습니다.', 'latest_loaded_at': get_latest_loaded_at(),
               'filters': {'lot_type': [], 'product': [], 'proc_id': [], 'issue_category': [], 'need_check': []},
               'summary_sections': [], 'lot_balance': {'labels': [], 'datasets': []}, 'index_chart': {'labels': [], 'datasets': []},
               'issue_rows': [], 'wip_rows': [], 'pagination': {'page': 1, 'page_size': 100, 'total': 0}}
        if settings.DEBUG: out['error_detail'] = f'{exc.__class__.__name__}: {exc}'
        return make_json_safe(out)
