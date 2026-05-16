from collections import defaultdict
import logging

from django.db import DatabaseError, OperationalError, ProgrammingError

from .models import WipMoveGroup, WipRefExclusionTypeRule, WipRefModuleRule, WipRefProductRule, WipReportLotPath
from .ref_services import area_from_eqp, classify_module, classify_product, parse_issue_eqp, parse_prevent

logger = logging.getLogger(__name__)


def build_summary(filters):
    try:
        qs = WipReportLotPath.objects.all()
        product_rules = list(WipRefProductRule.objects.filter(is_active=True).order_by('sort_no', 'id'))
        module_rules = list(WipRefModuleRule.objects.filter(is_active=True).order_by('sort_no', 'id'))
        ex_rules = list(WipRefExclusionTypeRule.objects.filter(is_active=True))
    except (ProgrammingError, OperationalError, DatabaseError) as exc:
        logger.exception('[summary-data 오류] %s: %s', exc.__class__.__name__, exc)
        return {
            'error': 'DB 연결 실패: MySQL 접속 정보를 확인해 주세요.',
            'error_detail': f'{exc.__class__.__name__}: {exc}',
        }

    lot_types = filters.get('lot_type') or ['PP']
    qs = qs.filter(lot_type__in=lot_types)
    rows = []
    for o in qs[:2000]:
        p = classify_product(o.lot_id, product_rules)
        rows.append({'lot_id': o.lot_id, 'product': p, 'proc_id': o.proc_id, 'layer_id': o.layer_id, 'step_seq': o.step_seq, 'status': o.status, 'cur_qty': o.cur_qty or 0, 'issue_eqp': o.issue_eqp or '', 'prevent': o.prevent or '', 'exclusion_type': o.exclusion_type or ''})
    lot_balance = defaultdict(lambda: defaultdict(float))
    for r in rows:
        m = classify_module(r['product'], r['layer_id'], r['step_seq'], module_rules)
        lot_balance[f"{r['layer_id']}|{m}"][r['status']] += r['cur_qty']
    issue = []
    for r in rows:
        for i in parse_issue_eqp(r['issue_eqp']):
            issue.append({'category': '설비이슈', 'issue': i['eqp'], 'status': f"{i['status']}({i['days']}일↑)", 'need_check': area_from_eqp(i['eqp']), 'qty': r['cur_qty'], 'lot': r['lot_id']})
        for p in parse_prevent(r['prevent']):
            issue.append({'category': 'TIP', 'issue': p['eqp'], 'status': f"PREVENT({p['days']}일↑)", 'need_check': area_from_eqp(p['eqp']), 'qty': r['cur_qty'], 'lot': r['lot_id']})
        if r['exclusion_type']:
            issue.append({'category': 'EXCLUSION', 'issue': f"{r['layer_id']} {r['step_seq']}", 'status': '미정', 'need_check': '미정', 'qty': r['cur_qty'], 'lot': r['lot_id']})
    summary_text = '\n'.join([f"[B/N] {k}" for k, v in list(lot_balance.items())[:5]]) or '데이터가 없습니다.'
    return {
        'filters': {'lot_type_options': sorted(set([x.lot_type for x in WipReportLotPath.objects.exclude(lot_type__isnull=True)])), 'product_options': sorted(set([r['product'] for r in rows])), 'proc_id_options': sorted(set([r['proc_id'] for r in rows if r['proc_id']]))},
        'summary_text': summary_text,
        'lot_balance': lot_balance,
        'index_chart': {'labels': [], 'move': [], 'wt': [], 'hold_rate': [], 'hold_wait_rate': []},
        'issue_rows': issue[:200],
        'wip_rows': rows[:100],
        'pagination': {'page': 1, 'page_size': 100, 'total': len(rows)},
    }
