from collections import defaultdict, Counter
from datetime import date, datetime, timedelta
from decimal import Decimal
import logging
import re

from django.conf import settings
from django.db import connection
from django.db.models import Model, QuerySet

from .models import WipMoveGroup, WipRefHotLotRule, WipRefModuleRule, WipRefProductRule, WipReportLotPath
from .ref_services import area_from_eqp, classify_hot_lot, classify_module, classify_product, parse_prevent

logger = logging.getLogger(__name__)

BASE_FIELDS = [
    'sys_line_id', 'cur_line_id', 'eqpline', 'sysdate', 'lot_inform', 'lot_id', 'status', 'status_reason', 'grade', 'lot_type',
    'lot_level', 'cur_qty', 'carr_id', 'bay_name', 'proc_id', 'order_seq', 'sample_step_type', 'metal_status', 'layer_id',
    'step_level', 'continuous', 'step_seq', 'step_desc', 'recipe_id', 'tkintype', 'batch_kind', 'eqp_type', 'eqpgroup',
    'eqpgroup_cham', 'prevent', 'issue_eqp', 'input_elapsed_days', 'step_arrive_elapsed_days', 'last_event_elapsed_days',
    'start_date', 'last_tkout_date', 'step_arrive_date', 'last_event_date', 'exclusion_type'
]
STATUS_ORDER = ['HOLD', 'RUN', 'WAIT', 'WAIT(진행불가)']
STATUS_COLOR = {'HOLD': '#d9534f', 'RUN': '#337ab7', 'WAIT': '#3c9d3c', 'WAIT(진행불가)': '#e0ad00'}
MOVE_LOT_TYPES = {'PP', 'PB', 'PG'}


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


def _to_date(v):
    if not v:
        return None
    s = str(v).strip()
    for f in ('%Y-%m-%d', '%Y/%m/%d', '%Y%m%d'):
        try:
            return datetime.strptime(s[:10] if f != '%Y%m%d' else s[:8], f).date()
        except Exception:
            pass
    return None


def _parse_issue_eqp_blocks(text):
    s = (text or '').strip()
    if not s:
        return []
    label_pat = re.compile(r'(DOWN|PM|LOCAL)\s*:\s*', re.I)
    matches = list(label_pat.finditer(s))
    out = []
    for i, m in enumerate(matches):
        status = m.group(1).upper()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(s)
        body = s[start:end].strip(' /,')
        for eqp, elapsed in re.findall(r'([^,\(\)/]+?)\s*\((\d+(?:\.\d+)?)\s*일↑?\)', body):
            out.append({'status': status, 'eqp': eqp.strip(), 'days': float(elapsed)})
    return out


def _is_user_like(text):
    t = (text or '').strip()
    if not t:
        return True
    if re.search(r'mgr$', t, re.I):
        return True
    if re.match(r'^\d{8}_.+', t):
        return True
    if re.match(r'^[A-Za-z0-9_\-]+$', t) and len(t) <= 20 and ('user' in t.lower() or 'mgr' in t.lower()):
        return True
    return False


def _reason_summary(reason):
    r = (reason or '').strip()
    if (not r) or r == '-' or _is_user_like(r):
        return '상세 사유 미기입. 확인 필요'
    lo = r.lower()
    if '진행금지' in r:
        return '진행금지성 HOLD'
    if 'flow' in lo:
        return 'FLOW 금지/제한'
    if 'wait' in lo:
        return '대기 조건성 HOLD'
    return r[:40]


def _parse_exclusion_details(text):
    out = []
    for m in re.finditer(r'(HOLD|FTP|예약제외)\s*:\s*([^|;]+)', text or '', re.I):
        kind = m.group(1).upper()
        body = m.group(2).strip()
        parts = [p.strip() for p in body.split('/') if p.strip()]
        elapsed = _to_num(re.search(r'(\d+(?:\.\d+)?)\s*일', parts[-1]).group(1)) if parts and re.search(r'일', parts[-1]) else 0.0
        reason = ''
        if len(parts) >= 3:
            reason = '/'.join(parts[1:-1]).strip()
        elif len(parts) == 2:
            reason = parts[0] if not _is_user_like(parts[0]) else ''
        out.append({'kind': kind, 'reason': reason, 'elapsed': elapsed})
    return out


def make_json_safe(value):
    if isinstance(value, dict): return {str(k): make_json_safe(v) for k, v in value.items()}
    if isinstance(value, QuerySet): return [make_json_safe(v) for v in value]
    if isinstance(value, (list, tuple)): return [make_json_safe(v) for v in value]
    if isinstance(value, set): return [make_json_safe(v) for v in sorted(value, key=lambda x: str(x))]
    if isinstance(value, Decimal): return float(value)
    if isinstance(value, (datetime, date)): return value.isoformat()
    if isinstance(value, Model): return str(value)
    return value


def _build_summary_sections(rows):
    bn = defaultdict(lambda: {'wait': 0.0, 'hold': 0.0, 'blocked': 0.0, 'lots': set(), 'desc': '-', 'eqpgroups': set()})
    eqp = defaultdict(lambda: {'qty': 0.0, 'lots': set(), 'days': []})
    ex = defaultdict(lambda: {'qty': 0.0, 'lots': set(), 'reasons': [], 'elapsed': []})

    for r in rows:
        qty = _to_num(r.get('cur_qty')); lot = r.get('lot_id') or ''
        key = (r.get('proc_id') or '-', r.get('layer_id') or '-', str(r.get('step_seq') or '-'))
        st = r.get('status') or ''
        if st in ('WAIT', 'HOLD', 'WAIT(진행불가)'):
            x = bn[key]; x['lots'].add(lot); x['desc'] = r.get('step_desc') or '-'
            if r.get('eqpgroup'): x['eqpgroups'].add(r['eqpgroup'])
            if r.get('eqpgroup_cham'): x['eqpgroups'].add(r['eqpgroup_cham'])
            x['wait'] += qty if st == 'WAIT' else 0
            x['hold'] += qty if st == 'HOLD' else 0
            x['blocked'] += qty if st == 'WAIT(진행불가)' else 0
        for i in _parse_issue_eqp_blocks(r.get('issue_eqp') or ''):
            k = (i['eqp'], i['status'])
            eqp[k]['qty'] += qty; eqp[k]['lots'].add(lot); eqp[k]['days'].append(i['days'])
        for d in _parse_exclusion_details(r.get('exclusion_type') or ''):
            k = (r.get('proc_id') or '-', r.get('layer_id') or '-', str(r.get('step_seq') or '-'), d['kind'])
            ex[k]['qty'] += qty; ex[k]['lots'].add(lot); ex[k]['reasons'].append(_reason_summary(d['reason'])); ex[k]['elapsed'].append(d['elapsed'])

    bn_items = sorted(
        bn.items(), key=lambda kv: (kv[1]['wait'], kv[1]['blocked'], kv[1]['hold'], kv[1]['wait'] + kv[1]['blocked'] + kv[1]['hold']), reverse=True
    )[:5]
    bn_lines = []
    for (proc, layer, step), v in bn_items:
        total = int(v['wait'] + v['hold'] + v['blocked'])
        reason = '현재 Step 자체의 대기/보류 재공 집중'
        bn_lines.append(f"PROC: {proc}<br>Layer: {layer}<br>Step: {step} / DESC: {v['desc'] or '-'}<br>EQP Group: {', '.join(sorted(v['eqpgroups'])) if v['eqpgroups'] else '-'}<br>대기성 재공: {total}매({len(v['lots'])}Lot)<br>구성: WAIT {int(v['wait'])}매 / HOLD {int(v['hold'])}매 / WAIT(진행불가) {int(v['blocked'])}매<br>사유: {reason}")

    eqp_lines = [f"EQP: {k[0]}<br>상태: {k[1]} / 경과: {max(v['days'] or [0]):.1f}일↑<br>대기성 재공: {int(v['qty'])}매({len(v['lots'])}Lot)<br>확인필요: {area_from_eqp(k[0])}" for k, v in sorted(eqp.items(), key=lambda kv: kv[1]['qty'], reverse=True)[:5]] or ['해당 이슈 없음']
    ex_lines = []
    for k, v in sorted(ex.items(), key=lambda kv: kv[1]['qty'], reverse=True)[:5]:
        rep = Counter(v['reasons']).most_common(1)[0][0] if v['reasons'] else '상세 사유 미기입. 확인 필요'
        ex_lines.append(f"PROC: {k[0]}<br>Layer: {k[1]} / Step: {k[2]}<br>유형: {k[3]}<br>대기성 재공: {int(v['qty'])}매({len(v['lots'])}Lot)<br>대표 사유: {rep}<br>평균 경과: {(sum(v['elapsed'])/len(v['elapsed'])) if v['elapsed'] else 0:.1f}일↑")

    return [
        {'title': '[B/N] 병목 후보 Top 5', 'lines': bn_lines or ['해당 이슈 없음']},
        {'title': '[설비이슈] 설비 이슈 Top 5', 'lines': eqp_lines},
        {'title': '[TIP] Prevent Top 5', 'lines': ['-']},
        {'title': '[EXCLUSION] HOLD/FTP/예약제외 Top 5', 'lines': ex_lines or ['해당 이슈 없음']},
    ]


def build_lot_type_breakdown(rows):
    acc = defaultdict(lambda: {'wait': 0.0, 'hold': 0.0, 'blocked': 0.0, 'lots': set()})
    for r in rows:
        st = r.get('status') or ''
        if st not in ('WAIT', 'HOLD', 'WAIT(진행불가)'):
            continue
        lot_type = r.get('lot_type') or '미지정'
        qty = _to_num(r.get('cur_qty'))
        acc[lot_type]['lots'].add(r.get('lot_id') or '')
        if st == 'WAIT':
            acc[lot_type]['wait'] += qty
        elif st == 'HOLD':
            acc[lot_type]['hold'] += qty
        elif st == 'WAIT(진행불가)':
            acc[lot_type]['blocked'] += qty

    items = []
    for lot_type, v in acc.items():
        total = v['wait'] + v['hold'] + v['blocked']
        items.append({
            'lot_type': lot_type,
            'wait': int(v['wait']),
            'hold': int(v['hold']),
            'blocked': int(v['blocked']),
            'total': int(total),
            'lots': len({x for x in v['lots'] if x}),
        })
    items.sort(key=lambda x: x['total'], reverse=True)
    return items


def build_wip_issue_summary_rows(rows):
    bn = defaultdict(lambda: {'wait': 0.0, 'hold': 0.0, 'blocked': 0.0, 'lots': set(), 'desc': '-', 'eqps': set(), 'lot_types': defaultdict(float)})
    for r in rows:
        st = r.get('status') or ''
        if st not in ('WAIT', 'HOLD', 'WAIT(진행불가)'):
            continue
        qty = _to_num(r.get('cur_qty')); lot = r.get('lot_id') or ''
        key = (r.get('proc_id') or '-', r.get('layer_id') or '-', str(r.get('step_seq') or '-'))
        x = bn[key]
        x['lots'].add(lot)
        x['desc'] = r.get('step_desc') or '-'
        if r.get('eqpgroup'):
            x['eqps'].add(r['eqpgroup'])
        if r.get('eqpgroup_cham'):
            x['eqps'].add(r['eqpgroup_cham'])
        lot_type = r.get('lot_type') or '미지정'
        x['lot_types'][lot_type] += qty
        if st == 'WAIT':
            x['wait'] += qty
        elif st == 'HOLD':
            x['hold'] += qty
        elif st == 'WAIT(진행불가)':
            x['blocked'] += qty
    rows_out = []
    for (proc, layer, step), v in bn.items():
        total = v['wait'] + v['hold'] + v['blocked']
        lt_items = sorted(v['lot_types'].items(), key=lambda x: x[1], reverse=True)
        major_lot_type, major_qty = (lt_items[0] if lt_items else ('-', 0.0))
        rows_out.append({
            'proc_id': proc, 'layer_id': layer, 'step_seq': step, 'step_desc': v['desc'],
            'eqpgroups': sorted(v['eqps']), 'wait': int(v['wait']), 'hold': int(v['hold']), 'blocked': int(v['blocked']),
            'total': int(total), 'lot_count': len({x for x in v['lots'] if x}),
            'major_lot_type': major_lot_type, 'major_lot_type_ratio': (major_qty / total * 100) if total > 0 else 0.0,
        })
    rows_out.sort(key=lambda x: (x['total'], x['blocked'], x['hold'], x['wait']), reverse=True)
    return rows_out


def build_summary_card_issue_comments(issue_rows, lot_type_breakdown, selected_lot_types):
    if not issue_rows:
        return ['해당 이슈 없음']
    top = issue_rows[0]
    risk_part = '단순 대기 중심입니다.'
    if top['blocked'] >= top['wait'] or top['hold'] >= top['wait']:
        risk_part = 'WAIT 대비 WAIT(진행불가)/HOLD 비중이 높아 진행 차단 가능성이 큽니다.'
    lot_focus = ''
    if len(selected_lot_types) == 1:
        lot_focus = f"선택 lot_type({selected_lot_types[0]}) 기준으로 집계되었습니다."
    elif lot_type_breakdown:
        lead = lot_type_breakdown[0]
        total_all = sum(x['total'] for x in lot_type_breakdown) or 1
        if lead['total'] / total_all >= 0.45:
            lot_focus = f"전체 lot_type 중 {lead['lot_type']}에 대기성 총량이 집중되었습니다."
    eqp_text = ', '.join(top['eqpgroups']) if top['eqpgroups'] else '-'
    return [
        f"현재 B/N은 PROC/LAYER/STEP 기준 {top['proc_id']}/{top['layer_id']}/{top['step_seq']}({top['step_desc']})에 집중되어 있으며, {risk_part}",
        f"EQPGROUP 기준 {eqp_text} 구간에서 대기성 총량 {top['total']}매({top['lot_count']}Lot), 구성 WAIT {top['wait']} / WAIT(진행불가) {top['blocked']} / HOLD {top['hold']}입니다.",
        lot_focus or f"lot_type 기준 우세군은 {top['major_lot_type']}({top['major_lot_type_ratio']:.1f}%)이며 우선 확인이 필요합니다.",
    ]


def build_summary(params):
    try:
        requested_lot_types = params.getlist('lot_type') if hasattr(params, 'getlist') else []
        page_size = min(max(int((params.get('page_size') if hasattr(params, 'get') else None) or 200), 1), 500)
        product_rules = list(WipRefProductRule.objects.filter(is_active=True).order_by('sort_no', 'id'))
        module_rules = list(WipRefModuleRule.objects.filter(is_active=True).order_by('sort_no', 'id'))
        hot_rules = list(WipRefHotLotRule.objects.filter(is_active=True).order_by('sort_no', 'id'))

        all_rows = list(WipReportLotPath.objects.values(*BASE_FIELDS)[:5000])
        lot_type_options = sorted({r.get('lot_type') for r in all_rows if r.get('lot_type')})
        lot_types = requested_lot_types or ['PP']
        rows = [r for r in all_rows if (r.get('lot_type') in lot_types)]

        by_lot = {}
        for r in rows:
            lot = (r.get('lot_id') or '').strip()
            if lot and lot not in by_lot:
                by_lot[lot] = r
        uniq_rows = list(by_lot.values())

        by_layer_status = defaultdict(lambda: defaultdict(float))
        for r in rows:
            by_layer_status[str(r.get('layer_id') or '-')][r.get('status') or '-'] += _to_num(r.get('cur_qty'))
        labels = sorted(by_layer_status.keys(), key=lambda x: (len(x), x))
        lot_balance = {'labels': labels, 'datasets': [{'label': s, 'data': [int(by_layer_status[l].get(s, 0)) for l in labels], 'backgroundColor': STATUS_COLOR.get(s, '#999')} for s in STATUS_ORDER]}

        issue_acc = defaultdict(lambda: {'qty': 0.0, 'lots': set(), 'category': '', 'issue': '', 'status': '', 'need_check': ''})
        ex_group = defaultdict(lambda: {'qty': 0.0, 'lots': set(), 'elapsed': [], 'reasons': []})
        for r in uniq_rows:
            qty = _to_num(r.get('cur_qty')); lot = r.get('lot_id') or ''
            for i in _parse_issue_eqp_blocks(r.get('issue_eqp') or ''):
                k = ('설비이슈', i['eqp'], i['status'])
                a = issue_acc[k]; a.update({'category': '설비이슈', 'issue': i['eqp'], 'status': f"{i['status']}({i['days']:.1f}일↑)", 'need_check': area_from_eqp(i['eqp'])}); a['qty'] += qty; a['lots'].add(lot)
            for p in parse_prevent(r.get('prevent') or ''):
                k = ('TIP', p['eqp'], 'PREVENT')
                a = issue_acc[k]; a.update({'category': 'TIP', 'issue': p['eqp'], 'status': f"PREVENT({_to_num(p['days']):.1f}일↑)", 'need_check': area_from_eqp(p['eqp'])}); a['qty'] += qty; a['lots'].add(lot)
            for d in _parse_exclusion_details(r.get('exclusion_type') or ''):
                cat = _reason_summary(d['reason'])
                gk = (r.get('proc_id') or '-', r.get('layer_id') or '-', r.get('step_seq') or '-', d['kind'], cat)
                ex_group[gk]['qty'] += qty; ex_group[gk]['lots'].add(lot); ex_group[gk]['elapsed'].append(d['elapsed']); ex_group[gk]['reasons'].append(cat)

        for (proc, layer, step, kind, cat), v in sorted(ex_group.items(), key=lambda kv: (kv[1]['qty'], len(kv[1]['lots'])), reverse=True)[:20]:
            key = ('EXCLUSION', proc, layer, step, kind, cat)
            a = issue_acc[key]
            a.update({'category': 'EXCLUSION', 'issue': f'PROC {proc} / Layer {layer} / Step {step} / {cat}', 'status': f"{kind}({(sum(v['elapsed'])/len(v['elapsed'])) if v['elapsed'] else 0:.1f}일↑)", 'need_check': cat})
            a['qty'] += v['qty']; a['lots'] = set(v['lots'])

        issue_rows = [{**v, 'qty_text': f"{int(v['qty'])}매({len(v['lots'])}Lot)"} for v in issue_acc.values()]
        issue_rows.sort(key=lambda x: x['qty'], reverse=True)

        wip_rows = []
        for r in uniq_rows[:page_size]:
            item = {k: r.get(k) for k in BASE_FIELDS}
            item['product'] = classify_product(r.get('lot_id'), product_rules)
            item['module'] = classify_module(item['product'], r.get('layer_id'), r.get('step_seq'), module_rules)
            item['hot_type'] = classify_hot_lot(r.get('grade'), r.get('lot_inform'), hot_rules)
            wip_rows.append(item)

        base_date = _to_date(get_latest_loaded_at()) or date.today()
        move_rows = list(WipMoveGroup.objects.filter(lot_type__in=MOVE_LOT_TYPES).values('y', 'm', 'w', 'report_date', 'move'))
        by_date_move = defaultdict(float)
        by_month_days = defaultdict(list)
        by_week_days = defaultdict(list)
        for r in move_rows:
            rd = _to_date(r.get('report_date'))
            if not rd:
                continue
            by_date_move[rd] += _to_num(r.get('move'))
            by_month_days[(rd.year, rd.month)].append(rd)
            by_week_days[(rd.isocalendar().year, rd.isocalendar().week)].append(rd)

        labels, move_data = [], []
        for i in range(2, -1, -1):
            d = base_date.replace(day=1)
            m = d.month - i
            y = d.year
            while m <= 0:
                m += 12; y -= 1
            days = sorted(set(by_month_days.get((y, m), [])))
            avg = sum(by_date_move[x] for x in days) / len(days) if days else None
            labels.append(f'{m}월'); move_data.append(round(avg, 2) if avg is not None else None)
        for i in range(3, -1, -1):
            wd = base_date - timedelta(days=7 * i)
            yw = (wd.isocalendar().year, wd.isocalendar().week)
            days = sorted(set(by_week_days.get(yw, [])))
            avg = sum(by_date_move[x] for x in days) / len(days) if days else None
            labels.append(f'W{yw[1]}'); move_data.append(round(avg, 2) if avg is not None else None)
        for i in range(6, -1, -1):
            d = base_date - timedelta(days=i)
            labels.append(f'{d.month}/{d.day}')
            move_data.append(round(by_date_move.get(d, 0.0), 2) if d in by_date_move else None)

        latest_qty_rows = [r for r in all_rows if r.get('lot_type') in MOVE_LOT_TYPES]
        total_qty = sum(_to_num(r.get('cur_qty')) for r in latest_qty_rows) or 0
        hold_qty = sum(_to_num(r.get('cur_qty')) for r in latest_qty_rows if r.get('status') == 'HOLD')
        blocked_qty = sum(_to_num(r.get('cur_qty')) for r in latest_qty_rows if r.get('status') in ('HOLD', 'WAIT(진행불가)'))
        latest_move = by_date_move.get(base_date)
        wt = (latest_move / total_qty * 100) if latest_move is not None and total_qty > 0 else None
        hold_rate = (hold_qty / total_qty * 100) if total_qty > 0 else None
        blocked_rate = (blocked_qty / total_qty * 100) if total_qty > 0 else None
        ratios = [None] * len(labels)
        if labels:
            ratios[-1] = round(wt, 2) if wt is not None else None
        hold_arr = [None] * len(labels)
        blocked_arr = [None] * len(labels)
        if labels and hold_rate is not None:
            hold_arr[-1] = round(hold_rate, 2)
            blocked_arr[-1] = round(blocked_rate, 2)

        index_chart = {'labels': labels, 'datasets': [
            {'type': 'bar', 'label': 'move', 'data': move_data, 'yAxisID': 'y'},
            {'type': 'line', 'label': 'w/t', 'data': ratios, 'yAxisID': 'y1'},
            {'type': 'line', 'label': 'hold율[%]', 'data': hold_arr, 'yAxisID': 'y1'},
            {'type': 'line', 'label': 'hold+WAIT진행불가율[%]', 'data': blocked_arr, 'yAxisID': 'y1'},
        ]}
        logger.info('[wip] index_chart labels=%s', len(labels))
        logger.info('[wip] lot_type options count=%s', len(lot_type_options))
        logger.info('[wip] wip_rows column count=%s', len(wip_rows[0].keys()) if wip_rows else 0)

        bn_issue_rows = build_wip_issue_summary_rows(uniq_rows)
        lot_type_breakdown = build_lot_type_breakdown(uniq_rows)
        selected_lot_types = lot_types if lot_types else []
        summary_sections = _build_summary_sections(uniq_rows)
        if summary_sections:
            summary_sections[0]['lines'] = build_summary_card_issue_comments(bn_issue_rows, lot_type_breakdown, selected_lot_types)
        out = {'ok': True, 'latest_loaded_at': get_latest_loaded_at(), 'message': '', 'filters': {'lot_type': lot_type_options or ['PP'], 'product': sorted({classify_product(x.get('lot_id'), product_rules) for x in all_rows if x.get('lot_id')}), 'proc_id': sorted({x['proc_id'] for x in all_rows if x.get('proc_id')}), 'issue_category': ['설비이슈', 'TIP', 'EXCLUSION'], 'need_check': ['PHOTO', 'METRO', 'METAL', 'CMP', 'CLN', 'CVD', 'IMP', 'DIFF', '미정']}, 'summary_sections': summary_sections, 'lot_balance': lot_balance, 'index_chart': index_chart, 'issue_rows': issue_rows[:200], 'wip_rows': wip_rows, 'pagination': {'page': 1, 'page_size': page_size, 'total': len(uniq_rows)}, 'lot_type_breakdown': lot_type_breakdown, 'bn_issue_rows': bn_issue_rows[:10]}
        return make_json_safe(out)
    except Exception as exc:
        logger.exception('[summary-data 오류] %s: %s', exc.__class__.__name__, exc)
        out = {'ok': False, 'message': 'Summary 데이터 조회 중 오류가 발생했습니다.', 'latest_loaded_at': get_latest_loaded_at(), 'filters': {'lot_type': [], 'product': [], 'proc_id': [], 'issue_category': [], 'need_check': []}, 'summary_sections': [], 'lot_balance': {'labels': [], 'datasets': []}, 'index_chart': {'labels': [], 'datasets': []}, 'issue_rows': [], 'wip_rows': [], 'pagination': {'page': 1, 'page_size': 100, 'total': 0}}
        if settings.DEBUG: out['error_detail'] = f'{exc.__class__.__name__}: {exc}'
        return make_json_safe(out)
