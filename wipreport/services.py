from collections import defaultdict, Counter
from datetime import date, datetime
from decimal import Decimal
import logging
import re

from django.conf import settings
from django.db import connection
from django.db.models import Model, QuerySet

from .models import WipMoveGroup, WipRefExclusionTypeRule, WipRefHotLotRule, WipRefModuleRule, WipRefProductRule, WipReportLotPath
from .ref_services import area_from_eqp, classify_hot_lot, classify_module, classify_product, parse_issue_eqp, parse_prevent

logger = logging.getLogger(__name__)
WIP_FIELDS = ["lot_id", "status", "cur_qty", "lot_type", "proc_id", "layer_id", "step_seq", "step_desc", "order_seq", "continuous", "issue_eqp", "prevent", "exclusion_type", "grade", "lot_inform"]
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


def _parse_elapsed(text):
    m = re.search(r'(\d+(?:\.\d+)?)\s*일', text or '')
    return float(m.group(1)) if m else 0.0


def _parse_exclusion_details(text):
    out = []
    for kind, body in re.findall(r'(HOLD|FTP|예약제외)\s*[:\-]\s*([^/]+)', text or '', re.I):
        reason = ''
        rm = re.search(r'reason\s*[:=]\s*([^,\)]+)', body, re.I)
        if rm:
            reason = rm.group(1).strip()
        elif ',' in body:
            reason = body.split(',')[-1].strip()
        else:
            reason = body.strip()
        out.append({'kind': kind.upper(), 'reason': reason, 'elapsed': _parse_elapsed(body)})
    return out


def _reason_summary(reason):
    r = (reason or '').strip()
    if not r or r == '-':
        return '상세 사유 미기입. 확인 필요'
    lo = r.lower()
    if '진행금지' in r:
        return '진행금지성 HOLD'
    if 'flow' in lo:
        return 'FLOW 금지/제한'
    if 'wait' in lo:
        return '대기 조건성 HOLD'
    return r[:30]


def make_json_safe(value):
    if isinstance(value, dict): return {str(k): make_json_safe(v) for k, v in value.items()}
    if isinstance(value, QuerySet): return [make_json_safe(v) for v in value]
    if isinstance(value, (list, tuple)): return [make_json_safe(v) for v in value]
    if isinstance(value, set): return [make_json_safe(v) for v in sorted(value, key=lambda x: str(x))]
    if isinstance(value, Decimal): return float(value)
    if isinstance(value, (datetime, date)): return value.isoformat()
    if isinstance(value, Model): return str(value)
    return value


def _build_summary_sections(uniq_rows):
    bn = defaultdict(lambda: {"wait": 0.0, "hold": 0.0, "blocked": 0.0, "lots": set(), "proc": '-', "layer": '-', "step": '-', "desc": ''})
    eqp = defaultdict(lambda: {"qty": 0.0, "lots": set(), "days": [], "status": '', "area": '미정'})
    tip = defaultdict(lambda: {"qty": 0.0, "lots": set(), "days": [], "area": '미정'})
    ex = defaultdict(lambda: {"qty": 0.0, "lots": set(), "reasons": [], "elapsed": []})

    by_lot = defaultdict(list)
    for r in uniq_rows:
        by_lot[r.get('lot_id') or ''].append(r)
        qty = _to_num(r.get('cur_qty')); lot = r.get('lot_id') or ''; st = r.get('status') or ''
        key = (r.get('proc_id') or '-', r.get('layer_id') or '-', str(r.get('step_seq') or '-'))
        if st in ['WAIT', 'HOLD', 'WAIT(진행불가)']:
            b = bn[key]; b['proc'], b['layer'], b['step'], b['desc'] = key[0], key[1], key[2], r.get('step_desc') or ''
            b['lots'].add(lot); b['wait'] += qty if st == 'WAIT' else 0; b['hold'] += qty if st == 'HOLD' else 0; b['blocked'] += qty if st == 'WAIT(진행불가)' else 0
        for i in parse_issue_eqp(r.get('issue_eqp') or ''):
            k = (i.get('eqp') or '-', i.get('status') or '미정'); a = eqp[k]; a['qty'] += qty; a['lots'].add(lot); a['status'] = k[1]; a['days'].append(_to_num(i.get('days'))); a['area'] = area_from_eqp(k[0])
        for p in parse_prevent(r.get('prevent') or ''):
            k = p.get('eqp') or '-'; a = tip[k]; a['qty'] += qty; a['lots'].add(lot); a['days'].append(_to_num(p.get('days'))); a['area'] = area_from_eqp(k)
        for d in _parse_exclusion_details(r.get('exclusion_type') or ''):
            k = (r.get('proc_id') or '-', r.get('layer_id') or '-', str(r.get('step_seq') or '-'))
            a = ex[k]; a['qty'] += qty; a['lots'].add(lot); a['reasons'].append(_reason_summary(d['reason'])); a['elapsed'].append(d['elapsed'])

    bn_lines = []
    bn_items = sorted(bn.items(), key=lambda kv: kv[1]['wait'] + kv[1]['hold'] + kv[1]['blocked'], reverse=True)[:5]
    for (proc, layer, step), v in bn_items:
        total = int(v['wait'] + v['hold'] + v['blocked'])
        msg = f"PROC: {proc} / Layer: {layer} / Step: {step} | 대기성 재공: {total}매({len(v['lots'])}Lot) = WAIT {int(v['wait'])}매 + HOLD {int(v['hold'])}매 + WAIT(진행불가) {int(v['blocked'])}매"
        bn_lines.append(msg)
    if not bn_lines: bn_lines = ['해당 이슈 없음']

    follow_msgs = []
    for (proc, layer, step), _ in bn_items:
        lots = [lot for lot, rows in by_lot.items() if any((r.get('proc_id') or '-') == proc and (r.get('layer_id') or '-') == layer and str(r.get('step_seq') or '-') == step and (r.get('continuous') or '').startswith('연속첫') for r in rows)]
        for lot in lots[:3]:
            rows = sorted(by_lot[lot], key=lambda x: _to_num(x.get('order_seq')))
            for rr in rows:
                if _to_num(rr.get('order_seq')) <= 0: continue
                if rr.get('issue_eqp') or rr.get('prevent') or rr.get('exclusion_type') or (rr.get('status') == 'WAIT(진행불가)'):
                    follow_msgs.append(f"현재 대기 위치는 연속공정 첫 Step이나, 후속 연속공정 Step({rr.get('proc_id')}/{rr.get('layer_id')}/{rr.get('step_seq')}) 이슈로 진입 제한 가능성이 있습니다.")
                    break

    def _top(acc, fn):
        return [fn(k, v) for k, v in sorted(acc.items(), key=lambda kv: kv[1]['qty'], reverse=True)[:5]] or ['해당 이슈 없음']

    eqp_lines = _top(eqp, lambda k, v: f"EQP: {k[0]} / 상태: {v['status']} / 경과: {max(v['days'] or [0]):.1f}일↑ | 대기성 재공: {int(v['qty'])}매({len(v['lots'])}Lot), Area: {v['area']}")
    tip_lines = _top(tip, lambda k, v: f"EQP: {k} / 상태: PREVENT / 경과: {max(v['days'] or [0]):.1f}일↑ | 대기성 재공: {int(v['qty'])}매({len(v['lots'])}Lot)")
    ex_lines = _top(ex, lambda k, v: f"PROC: {k[0]} / Layer: {k[1]} / Step: {k[2]} | {int(v['qty'])}매({len(v['lots'])}Lot), 대표 사유: {Counter(v['reasons']).most_common(1)[0][0] if v['reasons'] else '미정'}, 평균 경과: {(sum(v['elapsed'])/len(v['elapsed'])) if v['elapsed'] else 0:.1f}일↑")

    if follow_msgs: bn_lines.extend(follow_msgs[:3])
    return [{"title": "[B/N] 병목 후보 Top 5", "lines": bn_lines}, {"title": "[설비이슈] 설비 이슈 Top 5", "lines": eqp_lines}, {"title": "[TIP] Prevent Top 5", "lines": tip_lines}, {"title": "[EXCLUSION] HOLD/FTP/예약제외 Top 5", "lines": ex_lines}]


def build_summary(params):
    try:
        lot_types = params.getlist('lot_type') if hasattr(params, 'getlist') else (params.get('lot_type') or ['PP'])
        lot_types = lot_types or ['PP']
        page_size = min(max(int((params.get('page_size') if hasattr(params, 'get') else None) or 200), 1), 500)
        product_rules = list(WipRefProductRule.objects.filter(is_active=True).order_by('sort_no', 'id'))
        module_rules = list(WipRefModuleRule.objects.filter(is_active=True).order_by('sort_no', 'id'))
        hot_rules = list(WipRefHotLotRule.objects.filter(is_active=True).order_by('sort_no', 'id'))

        rows = list(WipReportLotPath.objects.filter(lot_type__in=lot_types).values(*WIP_FIELDS)[:4000])
        by_lot = {}
        for r in rows:
            lot = (r.get('lot_id') or '').strip()
            if lot and lot not in by_lot: by_lot[lot] = r
        uniq_rows = list(by_lot.values())

        by_layer_status = defaultdict(lambda: defaultdict(float))
        for r in rows:
            by_layer_status[str(r.get('layer_id') or '-')][r.get('status') or '-'] += _to_num(r.get('cur_qty'))
        labels = sorted(by_layer_status.keys(), key=lambda x: (len(x), x))
        lot_balance = {"labels": labels, "datasets": [{"label": s, "data": [int(by_layer_status[l].get(s, 0)) for l in labels], "backgroundColor": STATUS_COLOR.get(s, '#999')} for s in STATUS_ORDER]}

        issue_acc = defaultdict(lambda: {'qty': 0.0, 'lots': set(), 'category': '', 'issue': '', 'status': '', 'need_check': ''})
        for r in uniq_rows:
            qty = _to_num(r.get('cur_qty')); lot = r.get('lot_id') or ''
            for i in parse_issue_eqp(r.get('issue_eqp') or ''):
                k = ('설비이슈', i['eqp'], i['status']); a = issue_acc[k]; a.update({'category': '설비이슈', 'issue': i['eqp'], 'status': f"{i['status']}({i['days']}일↑)", 'need_check': area_from_eqp(i['eqp'])}); a['qty'] += qty; a['lots'].add(lot)
            for p in parse_prevent(r.get('prevent') or ''):
                k = ('TIP', p['eqp'], 'PREVENT'); a = issue_acc[k]; a.update({'category': 'TIP', 'issue': p['eqp'], 'status': f"PREVENT({p['days']}일↑)", 'need_check': area_from_eqp(p['eqp'])}); a['qty'] += qty; a['lots'].add(lot)
            for d in _parse_exclusion_details(r.get('exclusion_type') or ''):
                issue = f"{r.get('proc_id') or '-'} / {r.get('layer_id') or '-'} / {r.get('step_seq') or '-'}"
                k = ('EXCLUSION', issue, d['kind']); a = issue_acc[k]; a.update({'category': 'EXCLUSION', 'issue': issue, 'status': f"{d['kind']}({d['elapsed']:.1f}일↑)", 'need_check': _reason_summary(d['reason'])}); a['qty'] += qty; a['lots'].add(lot)
        issue_rows = [{**v, 'qty_text': f"{int(v['qty'])}매({len(v['lots'])}Lot)"} for v in issue_acc.values()]
        issue_rows.sort(key=lambda x: x['qty'], reverse=True)

        wip_rows = []
        for r in uniq_rows[:page_size]:
            item = {k: r.get(k) for k in WIP_FIELDS if k not in {'issue_eqp', 'prevent', 'exclusion_type', 'lot_inform', 'grade'}}
            item['product'] = classify_product(r.get('lot_id'), product_rules)
            item['module'] = classify_module(item['product'], r.get('layer_id'), r.get('step_seq'), module_rules)
            item['hot_type'] = classify_hot_lot(r.get('grade'), r.get('lot_inform'), hot_rules)
            wip_rows.append(item)

        move_rows = list(reversed(list(WipMoveGroup.objects.values('report_date', 'move').order_by('-report_date')[:60])))
        idx_labels = [str(m['report_date']) for m in move_rows]
        move_data = [_to_num(m['move']) for m in move_rows]
        total_qty = sum(_to_num(r.get('cur_qty')) for r in uniq_rows) or 1
        hold_qty = sum(_to_num(r.get('cur_qty')) for r in uniq_rows if (r.get('status') or '') == 'HOLD')
        blocked_qty = sum(_to_num(r.get('cur_qty')) for r in uniq_rows if (r.get('status') or '') == 'WAIT(진행불가)')
        wait_qty = sum(_to_num(r.get('cur_qty')) for r in uniq_rows if (r.get('status') or '') == 'WAIT')
        idx_len = len(idx_labels)
        index_chart = {"labels": idx_labels, "datasets": [{"type": "bar", "label": "move", "data": move_data, "yAxisID": "y"}, {"type": "line", "label": "w/t", "data": [round(wait_qty / total_qty * 100, 2)] * idx_len, "yAxisID": "y1"}, {"type": "line", "label": "hold율[%]", "data": [round(hold_qty / total_qty * 100, 2)] * idx_len, "yAxisID": "y1"}, {"type": "line", "label": "hold+WAIT진행불가율[%]", "data": [round((hold_qty + blocked_qty) / total_qty * 100, 2)] * idx_len, "yAxisID": "y1"}]}

        out = {'ok': True, 'latest_loaded_at': get_latest_loaded_at(), 'message': '', 'filters': {'lot_type': sorted({x['lot_type'] for x in rows if x.get('lot_type')}) or ['PP'], 'product': sorted({classify_product(x.get('lot_id'), product_rules) for x in rows if x.get('lot_id')}), 'proc_id': sorted({x['proc_id'] for x in rows if x.get('proc_id')}), 'issue_category': ['설비이슈', 'TIP', 'EXCLUSION'], 'need_check': ['PHOTO', 'METRO', 'METAL', 'CMP', 'CLN', 'CVD', 'IMP', 'DIFF', '미정']}, 'summary_sections': _build_summary_sections(uniq_rows), 'lot_balance': lot_balance, 'index_chart': index_chart, 'issue_rows': issue_rows[:200], 'wip_rows': wip_rows, 'pagination': {'page': 1, 'page_size': page_size, 'total': len(uniq_rows)}}
        return make_json_safe(out)
    except Exception as exc:
        logger.exception('[summary-data 오류] %s: %s', exc.__class__.__name__, exc)
        out = {'ok': False, 'message': 'Summary 데이터 조회 중 오류가 발생했습니다.', 'latest_loaded_at': get_latest_loaded_at(), 'filters': {'lot_type': [], 'product': [], 'proc_id': [], 'issue_category': [], 'need_check': []}, 'summary_sections': [], 'lot_balance': {'labels': [], 'datasets': []}, 'index_chart': {'labels': [], 'datasets': []}, 'issue_rows': [], 'wip_rows': [], 'pagination': {'page': 1, 'page_size': 100, 'total': 0}}
        if settings.DEBUG: out['error_detail'] = f'{exc.__class__.__name__}: {exc}'
        return make_json_safe(out)
