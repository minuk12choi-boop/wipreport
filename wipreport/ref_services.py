import re

def classify_product(lot_id, product_rules):
    lot_id = lot_id or ''
    for r in product_rules:
        chars = [r.lot_char_1, r.lot_char_2, r.lot_char_3, r.lot_char_4, r.lot_char_5]
        ok = True
        for i, c in enumerate(chars):
            if c and (len(lot_id) <= i or lot_id[i] != c): ok = False
        if ok and (not r.processed or r.processed in lot_id):
            return r.product_name
    return '미분류'

def classify_module(product_name, layer_id, step_seq, module_rules):
    for r in module_rules:
        if r.product_name != product_name: continue
        step_ok = True if not (r.start_stepseq or r.end_stepseq) else (str(r.start_stepseq or r.end_stepseq) <= str(step_seq or '') <= str(r.end_stepseq or r.start_stepseq))
        layer_ok = True if not (r.start_layer or r.end_layer) else (str(r.start_layer or r.end_layer) <= str(layer_id or '') <= str(r.end_layer or r.start_layer))
        if step_ok or (layer_ok and not (r.start_stepseq or r.end_stepseq)):
            return r.module_name
    return ''

def parse_issue_eqp(issue_eqp):
    out=[]
    for status in ['DOWN','PM','LOCAL']:
        for eqp, days in re.findall(fr'{status}:\s*([A-Z0-9_\-]+).*?\((\d+(?:\.\d+)?)일', issue_eqp or '', re.I):
            out.append({'eqp':eqp,'status':status,'days':float(days)})
    return out

def parse_prevent(prevent):
    return [{'eqp':e,'days':float(d)} for e,d in re.findall(r'PREVENT:\s*([A-Z0-9_\-]+).*?\((\d+(?:\.\d+)?)일', prevent or '', re.I)]

def parse_exclusion_type(exclusion_type):
    return [{'kind':k.lower(),'reason':r} for k,r in re.findall(r'(HOLD|FTP|예약제외)\s*[:\-]\s*(.+)', exclusion_type or '', re.I)]

def classify_exclusion_type(exclusion_type, exclusion_rules):
    lines = parse_exclusion_type(exclusion_type)
    for r in exclusion_rules:
        for line in lines:
            if line['kind'] != (r.exclusion_kind or '').lower(): continue
            txt = line['reason']
            conds=[r.condition_1,r.condition_2,r.condition_3]
            if all((not c) or (c in txt) for c in conds): return r.type_name
    return ''

def classify_hot_lot(grade, lot_inform, hot_rules):
    txt = lot_inform or ''
    for r in hot_rules:
        if r.grade and r.grade != (grade or ''): continue
        if all((not c) or (c in txt) for c in [r.condition_1,r.condition_2,r.condition_3]): return r.type_name
    return ''

def area_from_eqp(eqp_name):
    return {'P':'PHOTO','M':'METRO','S':'METAL','C':'CMP','W':'CLN','T':'CVD','I':'IMP','D':'DIFF','F':'IMP'}.get((eqp_name or ' ')[:1], '미정')
