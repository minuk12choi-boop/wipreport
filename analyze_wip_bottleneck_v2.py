import pandas as pd
import numpy as np
import sys
import io
import re
from collections import defaultdict

# Set UTF-8 encoding for output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Read the Excel file
file_path = r'D:\PERSONAL_SPACE\SW\python\4_zhbm\output_wip_concat.xlsx'
df = pd.read_excel(file_path)

print("=" * 80)
print("WIP DATA ANALYSIS - BOTTLENECK IDENTIFICATION (V2)")
print("=" * 80)

# Display basic info
print("\n[1] BASIC INFORMATION")
print(f"Total rows: {len(df)}")
print(f"Total columns: {len(df.columns)}")
print(f"\nColumn names: {list(df.columns)}")

# Check for key columns
print("\n[2] KEY COLUMNS CHECK")
key_cols = ['lot_id', 'order_seq', 'step_seq', 'proc_id', 'layer_id', 'step_desc', 'exclusion_type', 'issue_eqp', 'prevent', 'eqpgroup', 'eqpgroup_cham', '연속', 'cur_qty']
for col in key_cols:
    if col in df.columns:
        print(f"  [OK] {col}: {df[col].notna().sum()} non-null values")
    else:
        print(f"  [X] {col}: NOT FOUND")

# Normalize column names
df.columns = [str(c).strip().lower() for c in df.columns]

# Ensure cur_qty is numeric
if 'cur_qty' in df.columns:
    df['cur_qty'] = pd.to_numeric(df['cur_qty'], errors='coerce').fillna(0)

# Ensure order_seq is numeric for sorting
if 'order_seq' in df.columns:
    df['order_seq'] = pd.to_numeric(df['order_seq'], errors='coerce').fillna(0)

# Sort by lot_id, order_seq, step_seq
if all(col in df.columns for col in ['lot_id', 'order_seq', 'step_seq']):
    df = df.sort_values(['lot_id', 'order_seq', 'step_seq']).reset_index(drop=True)
    print("\n[3] DATA SORTING")
    print("  Sorted by lot_id, order_seq, step_seq")

# Handle first step counting: count only first occurrence of each lot_id
print("\n[4] FIRST STEP COUNTING")
if 'lot_id' in df.columns:
    # Mark first occurrence of each lot_id (like Excel COUNTIFS($G$2:G2, G2)=1)
    df['is_first_step'] = df.groupby('lot_id').cumcount() == 0
    first_step_count = df['is_first_step'].sum()
    print(f"  First step rows: {first_step_count}")
    
    # Calculate total WIP quantity for first steps only
    first_step_df = df[df['is_first_step']]
    total_wip_qty = first_step_df['cur_qty'].sum() if 'cur_qty' in first_step_df.columns else len(first_step_df)
    total_wip_lots = len(first_step_df)
    print(f"  Total WIP Quantity (first steps only): {total_wip_qty}")
    print(f"  Total WIP Lots (first steps only): {total_wip_lots}")
else:
    df['is_first_step'] = True
    first_step_df = df.copy()
    total_wip_qty = df['cur_qty'].sum() if 'cur_qty' in df.columns else len(df)
    total_wip_lots = len(df)

# Analyze bottleneck steps by quantity
print("\n[5] BOTTLENECK STEP ANALYSIS (BY QUANTITY)")
if 'step_seq' in first_step_df.columns:
    step_qty = first_step_df.groupby('step_seq')['cur_qty'].sum().sort_values(ascending=False).head(20)
    print("Top 20 steps by WIP quantity:")
    for step, qty in step_qty.items():
        print(f"  {step}: {qty} qty")

if 'proc_id' in first_step_df.columns:
    proc_qty = first_step_df.groupby('proc_id')['cur_qty'].sum().sort_values(ascending=False).head(20)
    print("\nTop 20 proc by WIP quantity:")
    for proc, qty in proc_qty.items():
        print(f"  {proc}: {qty} qty")

if 'layer_id' in first_step_df.columns:
    layer_qty = first_step_df.groupby('layer_id')['cur_qty'].sum().sort_values(ascending=False).head(20)
    print("\nTop 20 layer by WIP quantity:")
    for layer, qty in layer_qty.items():
        print(f"  {layer}: {qty} qty")

# Cross analysis: proc_id + layer_id + step_seq combination by quantity
if all(col in first_step_df.columns for col in ['proc_id', 'layer_id', 'step_seq']):
    print("\n[6] TOP BOTTLENECK COMBINATIONS (proc_id + layer_id + step_seq) BY QUANTITY")
    combo_qty = first_step_df.groupby(['proc_id', 'layer_id', 'step_seq'])['cur_qty'].sum().sort_values(ascending=False).head(20)
    for (proc, layer, stepseq), qty in combo_qty.items():
        # Get step_desc and eqpgroup for this combination
        mask = (first_step_df['proc_id'] == proc) & (first_step_df['layer_id'] == layer) & (first_step_df['step_seq'] == stepseq)
        subset = first_step_df[mask]
        step_desc = subset['step_desc'].iloc[0] if 'step_desc' in subset.columns and len(subset) > 0 else ''
        eqpgroup = subset['eqpgroup'].iloc[0] if 'eqpgroup' in subset.columns and len(subset) > 0 else ''
        print(f"  {proc} / {layer} / {stepseq}: {qty} qty")
        if step_desc:
            print(f"    Step Desc: {step_desc}")
        if eqpgroup:
            print(f"    EqpGroup: {eqpgroup}")

# Analyze exclusion_type with HOLD reasons
print("\n[7] EXCLUSION_TYPE ANALYSIS (WITH HOLD REASONS)")
if 'exclusion_type' in first_step_df.columns:
    print(f"Total non-null exclusion_type: {first_step_df['exclusion_type'].notna().sum()}")
    
    # Parse HOLD entries to extract reasons
    def parse_hold_reason(exclusion):
        if pd.isna(exclusion):
            return None, None
        exclusion_str = str(exclusion)
        
        # Check if it's a HOLD
        if 'HOLD:' in exclusion_str:
            # Extract the HOLD type (before the first colon after HOLD:)
            hold_match = re.search(r'HOLD:\s*([^:]+)', exclusion_str)
            hold_type = hold_match.group(1).strip() if hold_match else 'HOLD'
            
            # Extract the reason (after the HOLD type)
            reason_match = re.search(r'HOLD:\s*[^:]+:\s*(.+)', exclusion_str)
            reason = reason_match.group(1).strip() if reason_match else ''
            
            return hold_type, reason
        return None, None
    
    first_step_df['hold_type'], first_step_df['hold_reason'] = zip(*first_step_df['exclusion_type'].apply(parse_hold_reason))
    
    # Count HOLD types
    hold_mask = first_step_df['hold_type'].notna()
    hold_counts = first_step_df[hold_mask]['hold_type'].value_counts().head(20)
    print("\nTop 20 HOLD types:")
    for hold_type, count in hold_counts.items():
        print(f"  {hold_type}: {count}")
    
    # Count HOLD reasons
    reason_counts = first_step_df[hold_mask]['hold_reason'].value_counts().head(20)
    print("\nTop 20 HOLD reasons:")
    for reason, count in reason_counts.items():
        print(f"  {reason}: {count}")

# Group HOLD bottlenecks by layer and adjacent step_seqs
print("\n[8] HOLD BOTTLENECK ANALYSIS (BY LAYER AND ADJACENT STEP_SEQS)")
if hold_mask.sum() > 0 and all(col in first_step_df.columns for col in ['proc_id', 'layer_id', 'step_seq', 'step_desc', 'hold_type', 'hold_reason']):
    # Group by layer and hold reason
    hold_by_layer = first_step_df[hold_mask].groupby(['proc_id', 'layer_id', 'hold_type', 'hold_reason']).agg({
        'cur_qty': 'sum',
        'step_seq': lambda x: list(sorted(set(x))),
        'step_desc': lambda x: list(set(x))
    }).sort_values('cur_qty', ascending=False).head(20)
    
    print("Top 20 HOLD bottlenecks by layer and reason:")
    for (proc_id, layer, hold_type, hold_reason), row in hold_by_layer.iterrows():
        step_seqs = row['step_seq']
        step_descs = row['step_desc']
        qty = row['cur_qty']
        print(f"  Proc {proc_id} | Layer {layer} | {hold_type}: {hold_reason}")
        print(f"    Step Seqs: {step_seqs}")
        if step_descs:
            print(f"    Step Descs: {step_descs}")
        print(f"    Total Qty: {qty}")

# Analyze issue_eqp (including continuous process issues)
print("\n[9] ISSUE_EQP ANALYSIS")
if 'issue_eqp' in df.columns:
    # Check issue_eqp in all rows (not just first steps)
    # For continuous process, if first step is waiting and later step has issue_eqp, it's a problem
    print(f"Total non-null issue_eqp: {df['issue_eqp'].notna().sum()}")
    
    # Get unique issue_eqp values
    issue_eqp_values = df[df['issue_eqp'].notna()]['issue_eqp'].unique()
    print(f"\nUnique issue_eqp values: {issue_eqp_values}")
    
    # Analyze issue_eqp by lot
    issue_eqp_by_lot = df[df['issue_eqp'].notna()].groupby('lot_id').agg({
        'issue_eqp': 'first',
        'step_seq': lambda x: list(x),
        'cur_qty': 'first',
        '연속': 'first',
        'proc_id': 'first',
        'layer_id': 'first',
        'step_desc': 'first'
    })
    
    print(f"\nIssue_eqp by lot ({len(issue_eqp_by_lot)} lots):")
    for lot_id, row in issue_eqp_by_lot.iterrows():
        issue_eqp = row['issue_eqp']
        step_seqs = row['step_seq']
        qty = row['cur_qty']
        is_continuous = row['연속']
        proc_id = row['proc_id']
        layer_id = row['layer_id']
        step_desc = row['step_desc']
        print(f"  Lot {lot_id}: {issue_eqp}")
        print(f"    Proc {proc_id} | Layer {layer_id} | Step {step_desc}")
        print(f"    Step Seqs: {step_seqs}")
        print(f"    Qty: {qty}")
        print(f"    Continuous: {is_continuous}")
    
    # Calculate total qty affected by issue_eqp
    issue_eqp_qty = df[df['issue_eqp'].notna()]['cur_qty'].sum()
    print(f"\nTotal qty affected by issue_eqp: {issue_eqp_qty}")

# Analyze prevent='PREVENT' issues
print("\n[10] PREVENT='PREVENT' ISSUES ANALYSIS")
if 'prevent' in df.columns:
    prevent_mask = df['prevent'].astype(str).str.upper().str.contains('PREVENT')
    prevent_count = prevent_mask.sum()
    print(f"Total rows with prevent='PREVENT': {prevent_count}")
    
    if prevent_count > 0:
        prevent_df = df[prevent_mask]
        print(f"\nPrevent='PREVENT' details:")
        for idx, row in prevent_df.iterrows():
            lot_id = row['lot_id'] if 'lot_id' in row else ''
            step_seq = row['step_seq'] if 'step_seq' in row else ''
            proc_id = row['proc_id'] if 'proc_id' in row else ''
            layer_id = row['layer_id'] if 'layer_id' in row else ''
            step_desc = row['step_desc'] if 'step_desc' in row else ''
            qty = row['cur_qty'] if 'cur_qty' in row else 0
            prevent = row['prevent'] if 'prevent' in row else ''
            print(f"  Lot {lot_id} | Proc {proc_id} | Layer {layer_id} | Step {step_seq} | Qty {qty}")
            print(f"    Step Desc: {step_desc}")
            print(f"    Prevent: {prevent}")

# Analyze NRDWAIT virtual step issue
print("\n[11] NRDWAIT VIRTUAL STEP ISSUE ANALYSIS")
if 'eqpgroup' in df.columns:
    nrdwait_mask = df['eqpgroup'].astype(str).str.upper() == 'NRDWAIT'
    nrdwait_count = nrdwait_mask.sum()
    print(f"Total rows with eqpgroup='NRDWAIT': {nrdwait_count}")
    
    if nrdwait_count > 0:
        nrdwait_df = df[nrdwait_mask]
        print(f"\nNRDWAIT details:")
        for idx, row in nrdwait_df.iterrows():
            lot_id = row['lot_id'] if 'lot_id' in row else ''
            step_seq = row['step_seq'] if 'step_seq' in row else ''
            proc_id = row['proc_id'] if 'proc_id' in row else ''
            layer_id = row['layer_id'] if 'layer_id' in row else ''
            step_desc = row['step_desc'] if 'step_desc' in row else ''
            qty = row['cur_qty'] if 'cur_qty' in row else 0
            status = row['status'] if 'status' in row else ''
            exclusion_type = row['exclusion_type'] if 'exclusion_type' in row else ''
            print(f"  Lot {lot_id} | Proc {proc_id} | Layer {layer_id} | Step {step_seq} | Qty {qty}")
            print(f"    Step Desc: {step_desc}")
            print(f"    Status: {status}")
            if pd.notna(exclusion_type):
                print(f"    Exclusion Type: {exclusion_type}")

# Analyze prevent tip not registered (eqpgroup vs eqpgroup_cham comparison)
print("\n[12] PREVENT TIP NOT REGISTERED ANALYSIS")
if all(col in df.columns for col in ['eqpgroup', 'eqpgroup_cham']):
    # Check if prevent tip is registered
    def check_prevent_tip_registered(row):
        eqpgroup = str(row['eqpgroup']).strip() if pd.notna(row['eqpgroup']) else ''
        eqpgroup_cham = str(row['eqpgroup_cham']).strip() if pd.notna(row['eqpgroup_cham']) else ''
        
        # If eqpgroup_cham has '-' (chamber equipment)
        if '-' in eqpgroup_cham:
            # Extract body names from eqpgroup_cham
            cham_bodies = set()
            for item in eqpgroup_cham.split(','):
                item = item.strip()
                if '-' in item:
                    body = item.split('-')[0].strip()
                    cham_bodies.add(body)
            
            # If eqpgroup has a body name that's not in eqpgroup_cham, tip is not registered
            # eqpgroup can have multiple bodies separated by comma
            eqpgroup_bodies = [b.strip() for b in eqpgroup.split(',') if b.strip()]
            missing_bodies = []
            for body in eqpgroup_bodies:
                if body not in cham_bodies:
                    missing_bodies.append(body)
            
            if missing_bodies:
                return False, ', '.join(missing_bodies)  # Tip not registered, return the missing bodies
        
        return True, None  # Tip registered or not applicable
    
    df['tip_registered'], df['missing_tip_body'] = zip(*df.apply(check_prevent_tip_registered, axis=1))
    
    tip_not_registered_mask = ~df['tip_registered']
    tip_not_registered_count = tip_not_registered_mask.sum()
    
    print(f"Total rows with tip not registered: {tip_not_registered_count}")
    
    if tip_not_registered_count > 0:
        tip_not_registered_df = df[tip_not_registered_mask]
        print(f"\nTip not registered details:")
        for idx, row in tip_not_registered_df.iterrows():
            lot_id = row['lot_id'] if 'lot_id' in row else ''
            step_seq = row['step_seq'] if 'step_seq' in row else ''
            proc_id = row['proc_id'] if 'proc_id' in row else ''
            layer_id = row['layer_id'] if 'layer_id' in row else ''
            eqpgroup = row['eqpgroup'] if 'eqpgroup' in row else ''
            eqpgroup_cham = row['eqpgroup_cham'] if 'eqpgroup_cham' in row else ''
            missing_body = row['missing_tip_body'] if 'missing_tip_body' in row else ''
            qty = row['cur_qty'] if 'cur_qty' in row else 0
            print(f"  Lot {lot_id} | Proc {proc_id} | Layer {layer_id} | Step {step_seq} | Qty {qty}")
            print(f"    EqpGroup: {eqpgroup}")
            print(f"    EqpGroup_Cham: {eqpgroup_cham}")
            print(f"    Missing Tip Body: {missing_body}")

# Generate summary data for report
print("\n" + "=" * 80)
print("SUMMARY DATA FOR REPORT")
print("=" * 80)

summary_data = {
    'total_wip_qty': total_wip_qty,
    'total_wip_lots': total_wip_lots,
    'top_bottlenecks': combo_qty.head(10).to_dict() if 'combo_qty' in locals() else {},
    'hold_bottlenecks': hold_by_layer.head(10).to_dict() if 'hold_by_layer' in locals() else {},
    'issue_eqp': {
        'count': len(issue_eqp_by_lot) if 'issue_eqp_by_lot' in locals() else 0,
        'qty': issue_eqp_qty if 'issue_eqp_qty' in locals() else 0,
        'details': issue_eqp_by_lot.to_dict() if 'issue_eqp_by_lot' in locals() else {}
    },
    'prevent_issues': {
        'count': prevent_count if 'prevent_count' in locals() else 0
    },
    'nrdwait_issues': {
        'count': nrdwait_count if 'nrdwait_count' in locals() else 0
    },
    'tip_not_registered': {
        'count': tip_not_registered_count if 'tip_not_registered_count' in locals() else 0
    }
}

print("\nSummary data prepared for report generation.")
print("\n" + "=" * 80)
print("ANALYSIS COMPLETE")
print("=" * 80)
