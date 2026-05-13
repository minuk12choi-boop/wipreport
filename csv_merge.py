import pandas as pd
import glob, re
import os

# CSV_DIR = r"C:\Users\minuk12.choi\Downloads\CSVMERGE"

import os, glob, re
import pandas as pd

CSV_DIR = r"C:\Users\minuk12.choi\Downloads\CSVMERGE"
OUT = os.path.join(CSV_DIR, "merged_fixed_schema.csv")
REPORT = os.path.join(CSV_DIR, "merge_fixed_schema_report.txt")

TARGET_COLS = [
    "SYSDATE", "LOT_ID", "QTY", "LOT_TYPE", "PROCESS_ID", "경과시간[일]",
    "DROPMOVE", "LAYERID", "STEP_SEQ", "STEP_DESC", "STATUS", "STEPSTATUS",
    "ISSUE", "EQPGROUP", "LAST_TKOUT_DATE"
]

SEP_CANDIDATES = [",", "\t", ";", "|"]

# 1) 인코딩 추정 (BOM 우선)
def detect_encoding_by_bom(path: str) -> str:
    with open(path, "rb") as f:
        b = f.read(4)
    if b.startswith(b"\xff\xfe") or b.startswith(b"\xfe\xff"):
        return "utf-16"
    if b.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    for enc in ["utf-8", "cp949", "euc-kr", "latin1"]:
        try:
            with open(path, "r", encoding=enc) as _:
                return enc
        except:
            pass
    return "latin1"

# 2) 샘플 라인 읽기
def sample_lines(path: str, enc: str, max_lines: int = 80):
    lines = []
    with open(path, "r", encoding=enc, errors="replace") as f:
        for _ in range(max_lines):
            line = f.readline()
            if not line:
                break
            s = line.strip("\r\n")
            if s.strip() == "":
                continue
            lines.append(s)
    return lines

# 3) sep + skiprows 추정
def choose_sep_and_skiprows(lines):
    if not lines:
        return None, 0

    sep_counts = {}
    for sep in SEP_CANDIDATES:
        sep_counts[sep] = [ln.count(sep) for ln in lines]

    best_sep, best_mid, best_nonzero = None, -1, -1
    for sep, counts in sep_counts.items():
        nonzero = sum(c > 0 for c in counts)
        mid = sorted(counts)[len(counts)//2]
        if (mid, nonzero) > (best_mid, best_nonzero):
            best_sep, best_mid, best_nonzero = sep, mid, nonzero

    if best_nonzero == 0:
        return None, 0

    counts = sep_counts[best_sep]
    start = 0
    for i, c in enumerate(counts):
        if c > 0:
            start = i
            break
    return best_sep, start

# 4) 컬럼명 정규화: 대문자, 공백/특수문자 제거(한글은 유지)
def norm_col(s: str) -> str:
    if s is None:
        return ""
    s = str(s).strip()
    s = s.replace("\ufeff", "")  # BOM 문자 제거
    # 한글은 유지하되, 영문/숫자/한글/대괄호만 남기고 나머지 제거
    s_up = s.upper()
    s_up = re.sub(r"[^\w가-힣\[\]]+", "", s_up)
    return s_up

# 5) 다양한 헤더명을 TARGET_COLS로 매핑 (필요하면 여기만 추가)
#    키: TARGET_COL, 값: 후보 컬럼명(정규화된 형태)
COL_MAP = {
    "SYSDATE": ["SYSDATE", "SYS_DATE", "DATE", "DT", "기준일", "일자"],
    "LOT_ID": ["LOT_ID", "LOTID", "LOT"],
    "QTY": ["QTY", "CUR_QTY", "CURQTY", "QTYPCS", "수량"],
    "LOT_TYPE": ["LOT_TYPE", "LOTTYPE", "LOTTP", "TYPE", "LOT_TYPECD"],
    "PROCESS_ID": ["PROCESS_ID", "PROC_ID", "PROC", "PROCESS", "PROCESSID"],
    "경과시간[일]": ["경과시간[일]", "경과시간일", "ELAPSED", "ELAPSEDDAY", "AGING", "AGE", "DAYS"],
    "DROPMOVE": ["DROPMOVE", "DROP_MOVE", "DROP"],
    "LAYERID": ["LAYERID", "LAYER_ID", "LAYER"],
    "STEP_SEQ": ["STEP_SEQ", "STEPSEQ", "STEP", "STEP_NO", "STEPSEQNO"],
    "STEP_DESC": ["STEP_DESC", "STEPDESC", "DESCRIPT", "DESC", "STEP_DESCRIPTION"],
    "STATUS": ["STATUS", "LOT_STATUS", "LOTSTATUS"],
    "STEPSTATUS": ["STEPSTATUS", "STEP_STATUS", "STEPSTAT"],
    "ISSUE": ["ISSUE", "ISSUEFLAG", "ISSUE_FLAG", "TIP_ISSUE"],
    "EQPGROUP": ["EQPGROUP", "EQP_GROUP", "EQPTYPE", "EQP_TYPE", "GROUP"],
    "LAST_TKOUT_DATE": ["LAST_TKOUT_DATE", "LASTTKOUTDATE", "LAST_TK_OUT_DATE", "TKOUT_DATE", "LAST_EVENT_DATE", "LASTEVENTDATE"]
}

# 후보도 정규화해두기
COL_MAP_NORM = {k: [norm_col(x) for x in v] for k, v in COL_MAP.items()}

def read_csv_smart(path: str, chunksize=200_000):
    enc = detect_encoding_by_bom(path)
    lines = sample_lines(path, enc)
    sep, skiprows = choose_sep_and_skiprows(lines)
    if sep is None:
        raise ValueError("delimiter_not_detected")

    it = pd.read_csv(
        path,
        encoding=enc,
        sep=sep,
        engine="python",
        on_bad_lines="skip",
        skiprows=skiprows,
        chunksize=chunksize
    )
    return it, enc, sep, skiprows

def normalize_and_select(df: pd.DataFrame):
    # 원본 컬럼 정규화 매핑: {정규화이름: 실제이름}
    orig_cols = list(df.columns)
    norm_to_orig = {}
    for c in orig_cols:
        nc = norm_col(c)
        # 충돌 시 앞 컬럼 우선
        if nc and nc not in norm_to_orig:
            norm_to_orig[nc] = c

    out = pd.DataFrame(index=df.index)

    # TARGET_COLS 순서대로 채움
    for tgt in TARGET_COLS:
        candidates = COL_MAP_NORM.get(tgt, [norm_col(tgt)])
        src = None
        for cand in candidates:
            if cand in norm_to_orig:
                src = norm_to_orig[cand]
                break
        if src is None:
            out[tgt] = pd.NA
        else:
            out[tgt] = df[src]

    return out

# --------- 병합 실행 ---------
csv_files = sorted(glob.glob(os.path.join(CSV_DIR, "*.csv")))
if not csv_files:
    raise RuntimeError("CSV 파일이 없습니다.")

if os.path.exists(OUT):
    os.remove(OUT)

report_lines = []
first = True
wrote_any = False

# 먼저 헤더만 생성(항상 OUT 생성 보장)
pd.DataFrame(columns=TARGET_COLS).to_csv(OUT, index=False, encoding="utf-8-sig")

for fp in csv_files:
    base = os.path.basename(fp)
    try:
        it, enc, sep, skiprows = read_csv_smart(fp, chunksize=200_000)
        file_rows = 0
        for chunk in it:
            # 매핑/정규화 후 필요한 컬럼만
            fixed = normalize_and_select(chunk)
            fixed.to_csv(OUT, mode="a", index=False, header=False, encoding="utf-8-sig")
            file_rows += len(fixed)
            wrote_any = True
        report_lines.append(f"{base} | OK | enc={enc} sep={repr(sep)} skiprows={skiprows} rows={file_rows}")
    except Exception as e:
        report_lines.append(f"{base} | FAIL | {type(e).__name__}: {e}")

with open(REPORT, "w", encoding="utf-8") as f:
    f.write("\n".join(report_lines))

print("OUT:", OUT)
print("REPORT:", REPORT)
print("wrote_any:", wrote_any)


# CSV_DIR = r"C:\Users\minuk12.choi\Downloads\CSVMERGE"
# OUTPUT_FILE = os.path.join(CSV_DIR, "merged.csv")

# csv_files = glob.glob(os.path.join(CSV_DIR, "*.csv"))

# def smart_read_csv(path, nrows=None, chunksize=None):
#     encodings = ["utf-8", "utf-16", "cp949", "euc-kr", "latin1"]

#     for enc in encodings:
#         try:
#             return pd.read_csv(path, encoding=enc, nrows=nrows, chunksize=chunksize)
#         except:
#             pass

#     raise Exception(f"❌ Cannot decode: {path}")

# # 1️⃣ 전체 컬럼 스캔
# all_columns = set()

# for f in csv_files:
#     df = smart_read_csv(f, nrows=1)
#     all_columns.update(df.columns)

# all_columns = sorted(all_columns)

# # 기존 파일 삭제
# if os.path.exists(OUTPUT_FILE):
#     os.remove(OUTPUT_FILE)

# # 2️⃣ 병합
# for i, f in enumerate(csv_files):
#     print("Merging:", f)

#     for chunk in smart_read_csv(f, chunksize=200_000):
#         chunk = chunk.reindex(columns=all_columns)

#         chunk.to_csv(
#             OUTPUT_FILE,
#             mode="a",
#             index=False,
#             header=(i == 0),
#             encoding="utf-8-sig"   # Excel 호환 UTF-8
#         )

# print("DONE:", OUTPUT_FILE)
