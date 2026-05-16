from __future__ import annotations

from pathlib import Path
import re
import warnings
import time

import pandas as pd
try:
    import pymysql
except ImportError:
    pymysql = None



EQP_PATH = r"C:\Users\minuk12.choi\Documents\eqpmaster.csv"
HOLD_PATH = r"C:\Users\minuk12.choi\Documents\hold.csv"
MCLOT_PATH = r"C:\Users\minuk12.choi\Documents\zhbm_mclot.csv"
STEPPATH_PATH = r"C:\Users\minuk12.choi\Documents\zhbm_steppath.csv"
TIP_PATH = r"C:\Users\minuk12.choi\Documents\tip.csv"

REQUIRED_COLUMNS = {
    "mclot": ["lot_id","proc_id","order_seq","step_seq","status","lot_inform","sysdate","cur_line_id","sys_line_id"],
    "steppath": ["lot_id","proc_id","order_seq","step_seq","eqp_id","recipe_id","de_rank","delay_step_type","연속"],
    "mcpath": ["lot_id","order_seq","step_seq","proc_id","eqp_id","recipe_id","status","lot_inform"],
    "eqpmaster": ["eqp_id", "batch_kind", "eqpline", "body_eqp_status", "body_status_change_time"],
    "tip": [
        "process",
        "step",
        "ppid",
        "eqpid",
        "eqpcham",
        "chamberid",
        "batch_kind",
        "prevent",
        "type_body",
        "type_cham",
        "tip_eventtime",
        "eqpissue",
        "body_eqp_status",
        "cham_eqp_status",
        "eqpissuetime",
        "eqpline",
    ],
    "hold": ["lot_id", "step_seq"],
}

ENCODING_CANDIDATES = ["utf-16", "utf-16-le", "utf-8-sig", "cp949", "euc-kr", "utf-8"]
SEP_CANDIDATES = [",", "\t", "|", ";"]
KEEP_STATUS_REASON = True

FINAL_CONCAT_COLUMNS = [
    "sys_line_id", "cur_line_id", "eqpline", "sysdate", "lot_inform", "lot_id", "status", "status_reason", "grade",
    "lot_type", "lot_level", "cur_qty", "carr_id", "bay_name", "proc_id", "order_seq", "sample_step_type",
    "metal_status", "layer_id", "step_level", "연속", "step_seq", "step_desc", "recipe_id", "tkintype",
    "batch_kind", "eqp_type", "eqpgroup", "eqpgroup_cham", "prevent", "issue_eqp", "투입경과일_일",
    "step도착경과_일", "마지막event경과_일", "start_date", "last_tkout_date", "step_arrive_date", "last_event_date",
    "exclusion_type",
]
FINAL_REQUIRED_CONCAT_COLUMNS = ["lot_inform", "lot_id", "step_seq", "order_seq", "status", "eqpgroup", "eqpgroup_cham", "prevent", "issue_eqp", "exclusion_type"]


class WipBuildError(Exception):
    pass


def quote_mysql_identifier(name: str) -> str:
    safe_name = str(name).replace("`", "``")
    return f"`{safe_name}`"


def dataframe_to_mysql_replace(df: pd.DataFrame, table_name: str = "wip_report_lotpath") -> None:
    if pymysql is None:
        print("오류:")
        print("pymysql이 설치되어 있지 않습니다.")
        print("아래 명령으로 설치 후 재실행하세요.")
        print("python -m pip install pymysql")
        raise RuntimeError("pymysql 미설치")

    print(f"[DB 적재] 대상 테이블: {table_name}")
    print(f"[DB 적재] 대상 rows: {len(df)}")
    print(f"[DB 적재] 대상 columns: {len(df.columns)}")

    conn = None
    cursor = None
    stage = "connect"
    try:
        conn = pymysql.connect(
            host="12.81.64.130",
            user="minuk12.choi",
            passwd="",
            port=3306,
            db="app_db",
            charset="utf8mb4",
        )
        cursor = conn.cursor()

        stage = "drop_table"
        quoted_table = quote_mysql_identifier(table_name)
        drop_sql = f"DROP TABLE IF EXISTS {quoted_table}"
        cursor.execute(drop_sql)
        print("[DB 적재] DROP TABLE 완료")

        stage = "create_table"
        col_defs = ",\n    ".join(
            f"{quote_mysql_identifier(col)} TEXT NULL" for col in df.columns
        )
        create_sql = (
            f"CREATE TABLE {quoted_table} (\n"
            f"    {col_defs}\n"
            ") CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
        )
        cursor.execute(create_sql)
        print("[DB 적재] 테이블 생성 완료")

        stage = "prepare_insert"
        cols_sql = ", ".join(quote_mysql_identifier(c) for c in df.columns)
        placeholders = ", ".join(["%s"] * len(df.columns))
        insert_sql = f"INSERT INTO {quoted_table} ({cols_sql}) VALUES ({placeholders})"
        prepared = df.where(pd.notna(df), None).copy()
        prepared = prepared.astype("object")
        for col in prepared.columns:
            prepared[col] = prepared[col].map(
                lambda v: v.strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, pd.Timestamp) else v
            )
        rows = [tuple(row) for row in prepared.itertuples(index=False, name=None)]

        stage = "insert"
        if rows:
            cursor.executemany(insert_sql, rows)
        print(f"[DB 적재] INSERT 완료: {len(rows)} rows")

        stage = "commit"
        conn.commit()
        print("[DB 적재] commit 완료")
    except Exception as exc:
        if conn is not None:
            conn.rollback()
        print(f"[DB 적재 오류] 단계: {stage}")
        print(f"[DB 적재 오류] 메시지: {exc}")
        raise RuntimeError(f"DB 적재 실패(단계: {stage})") from exc
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()
        print("[DB 적재] 연결 종료")


def add_load_metadata(df: pd.DataFrame) -> tuple[pd.DataFrame, str, str]:
    now = pd.Timestamp.now()
    loaded_at = now.strftime("%Y-%m-%d %H:%M:%S")
    loaded_id = now.strftime("%Y%m%d%H%M%S")
    out = df.copy()
    out["loaded_at"] = loaded_at
    out["loaded_id"] = loaded_id
    return out, loaded_at, loaded_id


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    return df


def _assert_required_columns(df: pd.DataFrame, name: str) -> None:
    missing = [c for c in REQUIRED_COLUMNS[name] if c not in df.columns]
    if missing:
        raise WipBuildError(f"필수 컬럼 누락: {name}에 {', '.join(missing)} 컬럼이 없습니다.")


def require_columns(df: pd.DataFrame, columns: list[str], name: str) -> None:
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise RuntimeError(f"{name} 필수 컬럼 누락: {missing}")


def assert_unique_columns(df: pd.DataFrame, name: str) -> None:
    dup_cols = df.columns[df.columns.duplicated()].tolist()
    if dup_cols:
        raise RuntimeError(f"{name}에 중복 컬럼명이 있습니다: {dup_cols[:20]}")


def normalize_join_key(series: pd.Series, *, numeric_normalize: bool = False) -> pd.Series:
    ser = series.astype("string").fillna("").str.strip()
    if not numeric_normalize:
        return ser
    num = pd.to_numeric(ser, errors="coerce")
    out = ser.copy()
    valid_num = num.notna()
    int_like = valid_num & (num % 1 == 0)
    out.loc[int_like] = num.loc[int_like].astype("Int64").astype("string")
    out.loc[valid_num & ~int_like] = num.loc[valid_num & ~int_like].map(lambda v: format(v, "g"))
    return out


def _build_encoding_order(signature: bytes) -> list[str]:
    if signature.startswith(b"\xff\xfe"):
        preferred = ["utf-16", "utf-16-le"]
    elif signature.startswith(b"\xfe\xff"):
        preferred = ["utf-16", "utf-16-be"]
    else:
        preferred = []

    ordered: list[str] = []
    for enc in preferred + ENCODING_CANDIDATES:
        if enc not in ordered:
            ordered.append(enc)
    return ordered


def _detect_sep(path: Path, encoding_order: list[str]) -> str:
    head = path.read_bytes()[:8192]
    best_sep = SEP_CANDIDATES[0]
    best_score = -1

    for enc in encoding_order:
        try:
            text = head.decode(enc)
        except UnicodeDecodeError:
            continue
        for sep in SEP_CANDIDATES:
            score = text.count(sep)
            if score > best_score:
                best_sep = sep
                best_score = score

    return best_sep


def _read_csv_with_fallback(path: Path, first_sep: str, encoding_order: list[str]) -> tuple[pd.DataFrame, str, str]:
    sep_order = [first_sep] + [s for s in SEP_CANDIDATES if s != first_sep]
    failed_cases: list[tuple[str, str, str]] = []
    for enc in encoding_order:
        for sep in sep_order:
            try:
                df = pd.read_csv(path, encoding=enc, sep=sep, dtype=str)
                if len(df.columns) <= 1 and path.stat().st_size > 0:
                    failed_cases.append((enc, repr(sep), "컬럼이 1개 이하로 읽혀 구분자 불일치 가능성"))
                    continue
                return df, enc, sep
            except Exception as exc:  # noqa: PERF203
                failed_cases.append((enc, repr(sep), str(exc)))

    summary_lines = []
    for enc, sep, reason in failed_cases[:8]:
        summary_lines.append(f"- encoding={enc}, sep={sep} -> {reason}")
    summary_text = "\n".join(summary_lines) if summary_lines else "- 시도 내역이 기록되지 않았습니다."
    raise WipBuildError(
        f"CSV 파일을 지원 인코딩/구분자 조합으로 읽지 못했습니다: {path}\n"
        f"[실패 요약 일부]\n{summary_text}"
    )


def read_input_csv(name: str, path: Path) -> tuple[pd.DataFrame, dict[str, str | int]]:
    if not path.exists():
        raise WipBuildError(f"원천 CSV 파일이 존재하지 않습니다: {path}")

    size = path.stat().st_size
    if size == 0:
        raise WipBuildError(f"{name} CSV 파일 크기가 0입니다.")

    head = path.read_bytes()[:256]
    print(f"[입력 확인] {name}: {path} / size={size} bytes / signature={head[:64]!r}")

    if head.startswith(b"<## NASCA DRM FILE - VER1.00 ##>"):
        raise WipBuildError(f"{name} 파일이 NASCA DRM 파일입니다. CSV로 다시 저장된 일반 텍스트 파일이 아닙니다.")

    encoding_order = _build_encoding_order(head)
    first_sep = _detect_sep(path, encoding_order)
    df, encoding, sep = _read_csv_with_fallback(path, first_sep, encoding_order)
    df = _normalize_columns(df)
    _assert_required_columns(df, name)

    meta = {
        "path": str(path),
        "size": size,
        "rows": len(df),
        "cols": len(df.columns),
        "encoding": encoding,
        "separator": repr(sep),
    }
    print(f"[CSV 읽기 성공] {name}: encoding={encoding}, sep={repr(sep)}, rows={len(df)}, cols={len(df.columns)}")
    print(f"[컬럼 확인] {name}: {df.columns.tolist()}")
    return df, meta


def _parse_single_datetime(value):
    text = _normalize_text(value)
    if not text:
        return pd.NaT

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        parsed = pd.to_datetime(text, errors="coerce")
    if pd.notna(parsed):
        return parsed

    normalized = re.sub(r"\s+", " ", text.strip())
    normalized = normalized.replace("/", "-")
    normalized = re.sub(r"\s*[-]\s*", "-", normalized)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        parsed = pd.to_datetime(normalized, errors="coerce")
    if pd.notna(parsed):
        return parsed

    digits = re.sub(r"\D", "", text)
    if len(digits) == 14:
        return pd.to_datetime(digits, format="%Y%m%d%H%M%S", errors="coerce")
    if len(digits) == 8:
        return pd.to_datetime(digits, format="%Y%m%d", errors="coerce")

    compact = re.sub(r"[^0-9\-: ]", "", normalized)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        return pd.to_datetime(compact, errors="coerce")


def safe_to_datetime(series: pd.Series) -> pd.Series:
    if series is None:
        return pd.Series(dtype="datetime64[ns]")
    ser = series if isinstance(series, pd.Series) else pd.Series(series)
    return ser.apply(_parse_single_datetime)


def log_datetime_parse_stats(label: str, raw_series: pd.Series, parsed_series: pd.Series, total: int | None = None) -> None:
    total_count = int(total if total is not None else len(raw_series))
    if total_count == 0:
        print(f"[{label}] 파싱 성공: 0 / 0")
        return
    non_blank = int(raw_series.map(lambda v: not is_blank(v)).sum()) if len(raw_series) else 0
    success = int(parsed_series.notna().sum()) if len(parsed_series) else 0
    print(f"[{label}] non-blank: {non_blank} / {total_count}")
    print(f"[{label}] 파싱 성공: {success} / {total_count}")


def _normalize_text(value) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, pd.Timestamp):
        if value.hour == 0 and value.minute == 0 and value.second == 0 and value.microsecond == 0:
            return value.strftime("%Y-%m-%d")
        return value.strftime("%Y-%m-%d %H:%M:%S")
    text = str(value).strip()
    if not text:
        return ""
    if text.lower() in {"nan", "none", "nat"}:
        return ""
    return text


def unique_concat_series(s: pd.Series):
    seen: set[str] = set()
    values: list[str] = []
    for v in s:
        text = _normalize_text(v)
        if not text or text in seen:
            continue
        seen.add(text)
        values.append(text)
    return ", ".join(values) if values else pd.NA




def sorted_unique_concat_series(s: pd.Series):
    values = sorted({_normalize_text(v) for v in s if _normalize_text(v)})
    return ", ".join(values) if values else pd.NA

def first_valid_value(s: pd.Series):
    for v in s:
        text = _normalize_text(v)
        if text:
            return v
    return pd.NA


def _to_datetime_value(value) -> pd.Timestamp | pd.NaT:
    return pd.to_datetime(value, errors="coerce")


def _elapsed_days_float(sysdate, target_date) -> float | pd.NA:
    sys_dt = _to_datetime_value(sysdate)
    tar_dt = _to_datetime_value(target_date)
    if pd.isna(sys_dt) or pd.isna(tar_dt):
        return pd.NA
    return round((sys_dt - tar_dt).total_seconds() / 86400.0, 1)


def calculate_day_diff(sysdate, target_date) -> float | pd.NA:
    return _elapsed_days_float(sysdate, target_date)


def format_elapsed_days_label(sysdate, target_date) -> str:
    diff = calculate_day_diff(sysdate, target_date)
    if pd.isna(diff):
        return "경과일계산불가"
    return f"{diff:.1f}일↑"


def get_older_datetime(a, b):
    a_dt = _to_datetime_value(a)
    b_dt = _to_datetime_value(b)
    if pd.isna(a_dt) and pd.isna(b_dt):
        return pd.NaT
    if pd.isna(a_dt):
        return b_dt
    if pd.isna(b_dt):
        return a_dt
    return min(a_dt, b_dt)


def make_prevent_item(row: pd.Series):
    body_type = _normalize_text(row.get("tip_type_body")).upper()
    cham_type = _normalize_text(row.get("tip_type_cham")).upper()
    eqp_id = _normalize_text(row.get("eqp_id"))
    tip_eqpcham = _normalize_text(row.get("tip_eqpcham"))
    elapsed = format_elapsed_days_label(row.get("sysdate"), row.get("tip_tip_eventtime"))

    if body_type == "PREVENT" and eqp_id:
        return f"{eqp_id}({elapsed})"
    if cham_type == "PREVENT" and tip_eqpcham:
        return f"{tip_eqpcham}({elapsed})"
    return pd.NA


def make_issue_items(row: pd.Series) -> dict[str, list[str]]:
    statuses = ["DOWN", "PM", "LOCAL"]
    out: dict[str, list[str]] = {k: [] for k in statuses}
    seen = {k: set() for k in statuses}

    issue_ref_time = get_older_datetime(row.get("eqpissuetime"), row.get("eqp_body_status_change_time"))

    def add_item(status_raw, eqp_name):
        status = _normalize_text(status_raw).upper()
        eqp = _normalize_text(eqp_name)
        if status not in statuses or not eqp:
            return
        elapsed = format_elapsed_days_label(row.get("sysdate"), issue_ref_time)
        item = f"{eqp}({elapsed})"
        if item not in seen[status]:
            seen[status].add(item)
            out[status].append(item)

    add_item(row.get("tip_body_eqp_status"), row.get("eqp_id"))
    add_item(row.get("body_eqp_status"), row.get("eqp_id"))
    add_item(row.get("tip_cham_eqp_status"), row.get("tip_eqpcham"))
    return out


def _unique_join_text(series: pd.Series) -> str | None:
    vals = [str(v).strip() for v in series.dropna() if str(v).strip()]
    uniq = list(dict.fromkeys(vals))
    return " | ".join(uniq) if uniq else None


def is_blank(value) -> bool:
    if pd.isna(value):
        return True
    text = str(value).strip()
    return text == "" or text.lower() in {"nan", "none", "nat"}


def normalize_text(value) -> str:
    if is_blank(value):
        return ""
    return str(value).strip().upper()


def is_o(value) -> bool:
    return normalize_text(value) == "O"


def is_bad_status(value) -> bool:
    return normalize_text(value) in {"LOCAL", "PM", "DOWN"}


def is_path_blocked(row: pd.Series) -> bool:
    return (
        normalize_text(row.get("tip_type_body")) == "PREVENT"
        or normalize_text(row.get("tip_type_cham")) == "PREVENT"
        or not is_blank(row.get("tip_eqpissue"))
        or not is_blank(row.get("eqpissue"))
        or is_bad_status(row.get("body_eqp_status"))
        or is_bad_status(row.get("tip_body_eqp_status"))
        or is_bad_status(row.get("tip_cham_eqp_status"))
    )


def group_all_paths_blocked(group_df: pd.DataFrame) -> bool:
    if group_df.empty:
        return False
    return bool(group_df.apply(is_path_blocked, axis=1).all())


def group_has_ftp_or_exception(group_df: pd.DataFrame) -> bool:
    if group_df.empty:
        return False
    return bool(group_df.apply(lambda r: is_o(r.get("ftp")) or is_o(r.get("예약제외")), axis=1).any())


def build_blocked_step_flags(wip: pd.DataFrame, group_keys: list[str]) -> pd.DataFrame:
    required_cols = group_keys + ["status", "연속"]
    for c in required_cols:
        if c not in wip.columns:
            raise WipBuildError(f"status 재판정 실패: 필수 컬럼 누락 - {c}")

    grouped = wip.groupby(group_keys, dropna=False, sort=False)
    rows: list[dict] = []
    for key, grp in grouped:
        key_dict = dict(zip(group_keys, key if isinstance(key, tuple) else (key,), strict=False))
        status_val = normalize_text(first_valid_value(grp["status"])) if "status" in grp.columns else ""
        cont_val = normalize_text(first_valid_value(grp["연속"])) if "연속" in grp.columns else ""
        rows.append({
            **key_dict,
            "all_paths_blocked": group_all_paths_blocked(grp),
            "has_ftp_or_exception": group_has_ftp_or_exception(grp),
            "is_wait": status_val == "WAIT",
            "is_continuous_first": cont_val == "연속첫".upper(),
            "blocked_by_later_continuous_step": False,
            "_order_num": pd.to_numeric(key_dict.get("order_seq"), errors="coerce"),
            "_group_pos": len(rows),
            "_lot_id_norm": normalize_text(key_dict.get("lot_id")),
        })

    flags = pd.DataFrame(rows)
    if flags.empty:
        return flags

    cont_map = (
        wip.assign(_lot_id_norm=wip["lot_id"].map(normalize_text), _cont_norm=wip["연속"].map(normalize_text))
        .groupby(group_keys, dropna=False, sort=False)["_cont_norm"]
        .agg(lambda s: any(v != "" for v in s))
        .reset_index(name="_is_continuous_step")
    )
    flags = flags.merge(cont_map, on=group_keys, how="left")
    flags["_is_continuous_step"] = flags["_is_continuous_step"].fillna(False)

    for _, lot_df in flags.groupby("_lot_id_norm", sort=False):
        if lot_df.empty:
            continue
        for idx, row in lot_df.iterrows():
            if not row["is_continuous_first"]:
                continue
            current_num = row["_order_num"]
            if not pd.isna(current_num):
                later = lot_df[(lot_df["_order_num"] > current_num) & (lot_df["_is_continuous_step"])]
            else:
                print("[status 재판정] 연속공정 후속 step 판정 기준 확인 필요")
                later = lot_df[(lot_df["_group_pos"] > row["_group_pos"]) & (lot_df["_is_continuous_step"])]
            later = later[later["all_paths_blocked"]]
            flags.at[idx, "blocked_by_later_continuous_step"] = not later.empty

    return flags.drop(columns=["_order_num", "_group_pos", "_lot_id_norm", "_is_continuous_step"], errors="ignore")


def apply_wait_blocked_status(wip_concat: pd.DataFrame, wip: pd.DataFrame, group_keys: list[str]) -> pd.DataFrame:
    flags = build_blocked_step_flags(wip, group_keys)
    if flags.empty:
        return wip_concat

    flags["wait_block_reason"] = pd.NA
    flags.loc[flags["has_ftp_or_exception"], "wait_block_reason"] = "FTP/예약제외"
    flags.loc[flags["wait_block_reason"].isna() & flags["all_paths_blocked"], "wait_block_reason"] = "현스텝 모든 path 진행불가"
    flags.loc[flags["wait_block_reason"].isna() & flags["blocked_by_later_continuous_step"], "wait_block_reason"] = "연속후속 step 진행불가"
    flags["will_block_wait"] = flags["is_wait"] & flags["wait_block_reason"].notna()

    wait_cnt = int(flags["is_wait"].sum())
    changed_cnt = int(flags["will_block_wait"].sum())
    cond1 = int((flags["is_wait"] & flags["has_ftp_or_exception"]).sum())
    cond2 = int((flags["is_wait"] & ~flags["has_ftp_or_exception"] & flags["all_paths_blocked"]).sum())
    cond3 = int((flags["is_wait"] & ~flags["has_ftp_or_exception"] & ~flags["all_paths_blocked"] & flags["blocked_by_later_continuous_step"]).sum())
    print(f"[status 재판정] WAIT 그룹 수: {wait_cnt}")
    print(f"[status 재판정] WAIT(진행불가) 변경 수: {changed_cnt}")
    print(f"[status 재판정] 조건1 FTP/예약제외: {cond1}")
    print(f"[status 재판정] 조건2 현스텝 모든 path 진행불가: {cond2}")
    print(f"[status 재판정] 조건3 연속후속 step 진행불가: {cond3}")

    out = wip_concat.merge(flags[group_keys + ["will_block_wait", "wait_block_reason", "is_wait"]], on=group_keys, how="left", validate="1:1")
    original_status = out["status"].copy() if "status" in out.columns else pd.Series([""] * len(out))
    out["status"] = out["status"].where(~out["will_block_wait"].fillna(False), "WAIT(진행불가)")
    if KEEP_STATUS_REASON:
        out["status_reason"] = out["wait_block_reason"]
    else:
        out = out.drop(columns=["status_reason"], errors="ignore")

    # 검증
    non_wait_changed = (out["is_wait"].fillna(False) == False) & (out["status"].astype(str) != original_status.astype(str))
    if non_wait_changed.any():
        raise WipBuildError("status 재판정 오류: WAIT이 아닌 그룹의 status가 변경되었습니다.")
    if not out["status"].astype(str).str.contains("WAIT\\(진행불가\\)", regex=True, na=False).any() and changed_cnt > 0:
        raise WipBuildError("status 재판정 오류: 변경 대상이 있었으나 결과 status 반영이 없습니다.")
    if "status" not in out.columns:
        raise WipBuildError("status 재판정 오류: status 컬럼이 사라졌습니다.")
    if KEEP_STATUS_REASON and "status_reason" not in out.columns:
        raise WipBuildError("status 재판정 오류: KEEP_STATUS_REASON=True 인데 status_reason 컬럼이 없습니다.")

    out = out.drop(columns=["will_block_wait", "wait_block_reason", "is_wait"], errors="ignore")
    print("[status 재판정] 완료")
    return out


def next_available_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    idx = 2
    while True:
        candidate = parent / f"{stem} ({idx}){suffix}"
        if not candidate.exists():
            return candidate
        idx += 1


def log_duplicate_keys(df: pd.DataFrame, keys: list[str], name: str, limit: int = 10, label: str = "[키 분포 점검]") -> None:
    missing = [c for c in keys if c not in df.columns]
    if missing:
        print(f"{label} {name}: 키 컬럼 누락 {missing}")
        return
    dup_mask = df.duplicated(subset=keys, keep=False)
    dup_rows = int(dup_mask.sum())
    dup_groups = int(df.loc[dup_mask, keys].drop_duplicates().shape[0]) if dup_rows else 0
    print(f"{label} {name}: keys={keys}, duplicated_rows={dup_rows}, duplicated_groups={dup_groups}")
    if dup_rows:
        print(df.loc[dup_mask, keys].value_counts().head(limit))


def _keynorm_series(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().str.upper()


def filter_tip_for_mcpath(tip_df: pd.DataFrame, mcpath_or_me: pd.DataFrame) -> pd.DataFrame:
    start = time.perf_counter()
    required_tip = ["process", "step", "ppid", "eqpid"]
    required_mc = ["proc_id", "step_seq", "recipe_id", "eqp_id"]
    require_columns(tip_df, required_tip, "tip 필터")
    require_columns(mcpath_or_me, required_mc, "mcpath/me 필터")

    tip_work = tip_df.copy()
    mc_work = mcpath_or_me.copy()
    for c in required_tip:
        tip_work[c] = _keynorm_series(tip_work[c])
    for c in required_mc:
        mc_work[c] = _keynorm_series(mc_work[c])

    proc_set = {v for v in mc_work["proc_id"].tolist() if v and v != "-"}
    step_set = {v for v in mc_work["step_seq"].tolist() if v and v != "-"}
    eqp_set = {v for v in mc_work["eqp_id"].tolist() if v and v != "-"}
    recipe_set = {v for v in mc_work["recipe_id"].tolist() if v and v != "-"}

    print(f"[tip 필터] 원본 tip rows: {len(tip_df)}")
    print(f"[tip 필터] mcpath unique proc_id: {len(proc_set)}")
    print(f"[tip 필터] mcpath unique step_seq: {len(step_set)}")
    print(f"[tip 필터] mcpath unique eqp_id: {len(eqp_set)}")
    print(f"[tip 필터] mcpath unique recipe_id: {len(recipe_set)}")

    eqpid_match = tip_work["eqpid"].isin(eqp_set)
    process_match = tip_work["process"].isin(proc_set) | tip_work["process"].eq("-")
    step_match = tip_work["step"].isin(step_set) | tip_work["step"].eq("-")
    ppid_match = tip_work["ppid"].isin(recipe_set) | tip_work["ppid"].eq("-")
    mask = eqpid_match & process_match & step_match & ppid_match
    tip_filtered = tip_df.loc[mask].copy()

    tip_filtered_norm = tip_work.loc[mask].copy()
    process_dash_cnt = int(tip_filtered_norm["process"].eq("-").sum())
    step_dash_cnt = int(tip_filtered_norm["step"].eq("-").sum())
    ppid_dash_cnt = int(tip_filtered_norm["ppid"].eq("-").sum())
    print(f"[tip 필터] process '-' rows 보존: {process_dash_cnt}")
    print(f"[tip 필터] step '-' rows 보존: {step_dash_cnt}")
    print(f"[tip 필터] ppid '-' rows 보존: {ppid_dash_cnt}")
    print(f"[tip 필터] 필터 후 tip rows: {len(tip_filtered)}")
    print(f"[tip 필터] 제거 rows: {len(tip_df) - len(tip_filtered)}")

    if len(tip_filtered) > len(tip_df):
        print("[경고] tip_filtered rows가 원본 tip rows를 초과했습니다. 필터 로직을 확인하세요.")
    if tip_filtered.empty:
        print("[경고] tip_filtered가 비어 있습니다.")
    if len(tip_filtered) > len(tip_df) * 0.5:
        print("[경고] tip 필터 후에도 원본 대비 50% 초과 rows가 남았습니다. 필터 조건을 확인하세요.")
    invalid_eqpid = int((~tip_filtered_norm["eqpid"].isin(eqp_set)).sum()) if not tip_filtered_norm.empty else 0
    if invalid_eqpid:
        print(f"[경고] tip_filtered 내 eqpid 후보 불일치 rows: {invalid_eqpid}")
    else:
        print("[tip 필터 검증] tip_filtered eqpid는 모두 mcpath.eqp_id 후보에 포함됩니다.")

    elapsed = time.perf_counter() - start
    print(f"[tip 필터] 필터 소요시간: {elapsed:.1f}초")
    print(f"[시간] tip 필터: {elapsed:.1f}초")
    return tip_filtered


def build_mcpath_from_raw_raw(mclot: pd.DataFrame, steppath: pd.DataFrame) -> pd.DataFrame:
    mcpath_columns = [
        "sysdate", "cur_line_id", "sys_line_id", "lot_inform", "lot_id", "carr_id", "grade", "lot_type", "lot_level",
        "cur_qty", "bay_name", "status", "proc_id", "order_seq", "sample_step_type", "metal_status", "de_rank",
        "delay_step_type", "연속", "layer_id", "step_level", "step_seq", "step_desc", "eqp_type", "eqp_group_raw",
        "eqp_id", "recipe_id", "tkintype", "tkin_type_detail", "start_date", "last_tkout_date", "step_arrive_date",
        "last_event_date",
    ]

    mclot_required = [
        "sysdate", "cur_line_id", "sys_line_id", "lot_inform", "lot_id", "grade", "carr_id", "lot_type", "lot_level",
        "cur_qty", "bay_name", "status", "proc_id", "order_seq", "step_seq", "start_date", "last_tkout_date",
        "step_arrive_date", "last_event_date",
    ]
    steppath_required = [
        "lot_id", "proc_id", "sample_step_type", "metal_status", "de_rank", "delay_step_type", "연속", "layer_id",
        "step_level", "order_seq", "step_seq", "step_desc", "eqp_type", "eqp_group_raw", "eqp_id", "recipe_id",
        "tkintype", "tkin_type_detail",
    ]

    def pick_col(df: pd.DataFrame, candidates: list[str], label: str, required: bool = True):
        for c in candidates:
            if c in df.columns:
                return df[c]
        if required:
            related = [c for c in df.columns if any(k in c.lower() for k in ["lot", "proc", "order", "step"])]
            raise RuntimeError(
                f"{label} 컬럼을 찾을 수 없습니다.\n"
                f"후보={candidates}\n"
                f"현재 관련 컬럼={related}"
            )
        return pd.Series(pd.NA, index=df.index, dtype="object")

    def validate_mcpath_columns(df: pd.DataFrame, name: str) -> None:
        assert_unique_columns(df, name)
        if df.columns.tolist() != mcpath_columns:
            raise RuntimeError(f"{name} 컬럼 순서/구성이 MCPATH_COLUMNS와 다릅니다.")

    def select_mcpath_columns_from_joined(joined: pd.DataFrame) -> pd.DataFrame:
        out = pd.DataFrame(index=joined.index)
        out["sysdate"] = pick_col(joined, ["sysdate_mclot", "sysdate"], "sysdate")
        out["cur_line_id"] = pick_col(joined, ["cur_line_id_mclot", "cur_line_id"], "cur_line_id")
        out["sys_line_id"] = pick_col(joined, ["sys_line_id_mclot", "sys_line_id"], "sys_line_id")
        out["lot_inform"] = pick_col(joined, ["lot_inform_mclot", "lot_inform"], "lot_inform")
        out["lot_id"] = pick_col(joined, ["lot_id_mclot", "lot_id", "lot_id_path"], "lot_id")
        out["carr_id"] = pick_col(joined, ["carr_id_mclot", "carr_id"], "carr_id")
        out["grade"] = pick_col(joined, ["grade_mclot", "grade"], "grade")
        out["lot_type"] = pick_col(joined, ["lot_type_mclot", "lot_type"], "lot_type")
        out["lot_level"] = pick_col(joined, ["lot_level_mclot", "lot_level"], "lot_level")
        out["cur_qty"] = pick_col(joined, ["cur_qty_mclot", "cur_qty"], "cur_qty")
        out["bay_name"] = pick_col(joined, ["bay_name_mclot", "bay_name"], "bay_name")
        out["status"] = pick_col(joined, ["status_mclot", "status"], "status")
        out["proc_id"] = pick_col(joined, ["proc_id_mclot", "proc_id", "proc_id_path"], "proc_id")
        out["order_seq"] = pick_col(joined, ["order_seq_path", "order_seq", "order_seq_mclot"], "order_seq")
        out["sample_step_type"] = pick_col(joined, ["sample_step_type_path", "sample_step_type"], "sample_step_type")
        out["metal_status"] = pick_col(joined, ["metal_status_path", "metal_status"], "metal_status")
        out["de_rank"] = pick_col(joined, ["de_rank_path", "de_rank"], "de_rank")
        out["delay_step_type"] = pick_col(joined, ["delay_step_type_path", "delay_step_type"], "delay_step_type")
        out["연속"] = pick_col(joined, ["연속_path", "연속"], "연속")
        out["layer_id"] = pick_col(joined, ["layer_id_path", "layer_id"], "layer_id")
        out["step_level"] = pick_col(joined, ["step_level_path", "step_level"], "step_level")
        out["step_seq"] = pick_col(joined, ["step_seq_path", "step_seq", "step_seq_mclot"], "step_seq")
        out["step_desc"] = pick_col(joined, ["step_desc_path", "step_desc"], "step_desc")
        out["eqp_type"] = pick_col(joined, ["eqp_type_path", "eqp_type"], "eqp_type")
        out["eqp_group_raw"] = pick_col(joined, ["eqp_group_raw_path", "eqp_group_raw"], "eqp_group_raw")
        out["eqp_id"] = pick_col(joined, ["eqp_id_path", "eqp_id"], "eqp_id")
        out["recipe_id"] = pick_col(joined, ["recipe_id_path", "recipe_id"], "recipe_id")
        out["tkintype"] = pick_col(joined, ["tkintype_path", "tkintype"], "tkintype")
        out["tkin_type_detail"] = pick_col(joined, ["tkin_type_detail_path", "tkin_type_detail"], "tkin_type_detail")
        out["start_date"] = pick_col(joined, ["start_date_mclot", "start_date"], "start_date")
        out["last_tkout_date"] = pick_col(joined, ["last_tkout_date_mclot", "last_tkout_date"], "last_tkout_date")
        out["step_arrive_date"] = pick_col(joined, ["step_arrive_date_mclot", "step_arrive_date"], "step_arrive_date")
        out["last_event_date"] = pick_col(joined, ["last_event_date_mclot", "last_event_date"], "last_event_date")
        out = out[mcpath_columns]
        validate_mcpath_columns(out, "현재 step mcpath")
        return out

    print(f"[mcpath 생성] mclot rows: {len(mclot)}")
    print(f"[mcpath 생성] steppath rows: {len(steppath)}")
    require_columns(mclot, mclot_required, "mclot")
    require_columns(steppath, steppath_required, "steppath")
    m = mclot.copy()
    p = steppath.copy()
    m["_lot_key"] = normalize_join_key(m["lot_id"])
    p["_lot_key"] = normalize_join_key(p["lot_id"])
    m["_order_key"] = normalize_join_key(m["order_seq"], numeric_normalize=True)
    p["_order_key"] = normalize_join_key(p["order_seq"], numeric_normalize=True)
    m["_de_rank_key"] = normalize_join_key(m.get("de_rank", pd.Series(pd.NA, index=m.index)), numeric_normalize=True)
    p["_de_rank_key"] = normalize_join_key(p["de_rank"], numeric_normalize=True)

    joined = m.merge(
        p, on=["_lot_key", "_order_key"], how="left", suffixes=("_mclot", "_path")
    )
    print(f"[mcpath 생성] 현재 step 조인 rows: {len(joined)}")
    joined_related_cols = [c for c in joined.columns if any(k in c.lower() for k in ["lot", "proc", "order", "step"])]
    print(f"[mcpath 생성] 현재 step joined columns 수: {len(joined.columns)}")
    print(f"[mcpath 생성] 현재 step joined columns 예시: {joined.columns.tolist()[:50]}")
    print(f"[mcpath 생성] 현재 step joined lot/proc/order/step 관련 columns: {joined_related_cols}")
    step_mismatch = (
        normalize_join_key(pick_col(joined, ["step_seq_mclot"], "step_seq_mclot", required=False))
        != normalize_join_key(pick_col(joined, ["step_seq_path", "step_seq"], "step_seq_path", required=False))
    )
    proc_mismatch = (
        normalize_join_key(pick_col(joined, ["proc_id_mclot"], "proc_id_mclot", required=False))
        != normalize_join_key(pick_col(joined, ["proc_id_path"], "proc_id_path", required=False))
    )
    print(f"[mcpath 생성] mclot.step_seq와 steppath.step_seq 불일치 rows: {int(step_mismatch.sum())}")
    print(f"[mcpath 생성] mclot.proc_id와 steppath.proc_id 불일치 rows: {int(proc_mismatch.sum())}")

    current_selected = select_mcpath_columns_from_joined(joined)
    delay_norm = current_selected["delay_step_type"].astype("string").fillna("").str.strip().str.upper()
    status_norm = current_selected["status"].astype("string").fillna("").str.strip().str.upper()
    expand_mask = (delay_norm == "S") & (status_norm != "RUN")
    expand_current = current_selected.loc[expand_mask].copy()
    keep_current = current_selected.loc[~expand_mask].copy()
    print(f"[mcpath 생성] 연속공정 확장 대상 rows: {len(expand_current)}")
    print(f"[mcpath 생성] keep_current rows: {len(keep_current)}")

    if expand_current.empty:
        expanded = pd.DataFrame(columns=mcpath_columns)
    else:
        expand_base = expand_current.copy()
        expand_base["_lot_key"] = normalize_join_key(expand_base["lot_id"])
        expand_base["_de_rank_key"] = normalize_join_key(expand_base["de_rank"], numeric_normalize=True)
        expand_joined = expand_base.merge(
            p, on=["_lot_key", "_de_rank_key"], how="left", suffixes=("_cur", "_path")
        )
        expand_related_cols = [c for c in expand_joined.columns if any(k in c.lower() for k in ["lot", "proc", "order", "step"])]
        print(f"[mcpath 생성] expanded joined columns 수: {len(expand_joined.columns)}")
        print(f"[mcpath 생성] expanded joined lot/proc/order/step 관련 columns: {expand_related_cols}")
        expanded = pd.DataFrame(index=expand_joined.index)
        for c in ["sysdate","cur_line_id","sys_line_id","lot_inform","lot_id","carr_id","grade","lot_type","lot_level","cur_qty","bay_name","status","proc_id","start_date","last_tkout_date","step_arrive_date","last_event_date"]:
            expanded[c] = pick_col(expand_joined, [f"{c}_cur", f"{c}_mclot", c, f"{c}_path"], c)
        for c in ["order_seq","sample_step_type","metal_status","de_rank","delay_step_type","연속","layer_id","step_level","step_seq","step_desc","eqp_type","eqp_group_raw","eqp_id","recipe_id","tkintype","tkin_type_detail"]:
            expanded[c] = pick_col(expand_joined, [f"{c}_path", f"{c}_steppath", c, f"{c}_cur"], c)
        expanded = expanded[mcpath_columns]
        validate_mcpath_columns(expanded, "연속확장 mcpath")
    print(f"[mcpath 생성] 연속공정 확장 후 rows: {len(expanded)}")

    validate_mcpath_columns(keep_current, "keep_current")
    validate_mcpath_columns(expanded, "expanded")
    print(f"[mcpath 생성] concat 전 keep_current rows: {len(keep_current)}")
    print(f"[mcpath 생성] concat 전 expanded rows: {len(expanded)}")
    mcpath = pd.concat([keep_current, expanded], ignore_index=True, sort=False)
    assert_unique_columns(mcpath, "최종 mcpath")
    mcpath = mcpath[mcpath_columns]
    if len(mcpath) == 0:
        raise RuntimeError("최종 mcpath row 수가 0입니다.")
    print(f"[mcpath 생성] 최종 mcpath rows: {len(mcpath)}")
    print(f"[mcpath 생성] 최종 mcpath columns 중복 여부: {bool(mcpath.columns.duplicated().any())}")
    print(f"[mcpath 생성] lot_inform 존재 여부: {'lot_inform' in mcpath.columns}")
    print(f"[mcpath 생성] lot_inform non-empty rows: {int(mcpath['lot_inform'].map(lambda v: not is_blank(v)).sum())}")
    validate_mcpath_columns(mcpath, "build_mcpath_from_raw_raw 결과")
    return mcpath


def build_wip(mcpath: pd.DataFrame, eqp: pd.DataFrame, tip: pd.DataFrame, hold: pd.DataFrame) -> pd.DataFrame:
    print(f"[행수 점검] mcpath 원본: {len(mcpath)}")
    print(f"[행수 점검] eqp 원본: {len(eqp)}")
    print(f"[행수 점검] tip 원본: {len(tip)}")
    print(f"[행수 점검] hold 원본: {len(hold)}")
    log_duplicate_keys(eqp, ["eqp_id"], "eqp 조인 키")
    log_duplicate_keys(hold, ["lot_id", "step_seq"], "hold 조인 키")
    log_duplicate_keys(hold, ["lot_id", "step_seq", "item_type"], "hold item_type 포함 키")

    eqp_renamed = eqp.rename(columns={
        "body_eqp_status": "eqp_body_eqp_status",
        "body_status_change_time": "eqp_body_status_change_time",
        "batch_kind": "eqp_batch_kind",
        "eqpline": "eqp_eqpline",
    })
    eqp_before = len(eqp_renamed)
    if "body_status_change_time" in eqp_renamed.columns:
        eqp_renamed["body_status_change_time_dt"] = safe_to_datetime(eqp_renamed["body_status_change_time"])
        if eqp_renamed["body_status_change_time_dt"].notna().any():
            eqp_renamed = eqp_renamed.sort_values("body_status_change_time_dt").drop_duplicates("eqp_id", keep="last")
        else:
            eqp_renamed = eqp_renamed.drop_duplicates("eqp_id", keep="last")
        eqp_renamed = eqp_renamed.drop(columns=["body_status_change_time_dt"])
    else:
        eqp_renamed = eqp_renamed.drop_duplicates("eqp_id", keep="last")
    print(f"[축약 점검] eqp 축약 전/후 rows: {eqp_before} -> {len(eqp_renamed)}")

    before_rows = len(mcpath)
    me = mcpath.merge(
        eqp_renamed[["eqp_id", "eqp_batch_kind", "eqp_eqpline", "eqp_body_eqp_status", "eqp_body_status_change_time"]],
        on="eqp_id",
        how="left",
    )
    after_rows = len(me)
    print(f"[행수 점검] mcpath + eqp 조인 후 rows: {after_rows}")
    print(f"[중복 점검] mcpath + eqp 조인 후 완전중복 rows: {me.duplicated().sum()}")
    if after_rows != before_rows:
        raise WipBuildError(f"mcpath + eqp 조인 후 행 수가 증가했습니다. before={before_rows}, after={after_rows}. eqp 조인키 중복 축약 로직을 확인하세요.")

    tip_renamed = tip.rename(columns={
        "body_eqp_status": "tip_body_eqp_status",
        "cham_eqp_status": "tip_cham_eqp_status",
        "batch_kind": "tip_batch_kind",
        "eqpline": "tip_eqpline",
        "eqpissuetime": "tip_eqpissuetime",
        "eqpissue": "tip_eqpissue",
        "eqpcham": "tip_eqpcham",
        "chamberid": "tip_chamberid",
        "prevent": "tip_prevent",
        "type_body": "tip_type_body",
        "type_cham": "tip_type_cham",
        "tip_eventtime": "tip_tip_eventtime",
    })
    for c in ["process", "step", "ppid", "eqpid"]:
        if c in tip_renamed.columns:
            tip_renamed[c] = _keynorm_series(tip_renamed[c])
    for c in ["proc_id", "step_seq", "recipe_id", "eqp_id"]:
        if c in me.columns:
            me[c] = _keynorm_series(me[c])

    tip_filtered = filter_tip_for_mcpath(tip_renamed, me)
    log_duplicate_keys(tip_filtered, ["process", "step", "eqpid", "ppid", "tip_eqpcham", "tip_chamberid"], "exact tip 조인 키(필터 후, 챔버 포함)")

    tip_cols = [
        "tip_eqpcham", "tip_chamberid", "tip_batch_kind", "tip_prevent", "tip_type_body", "tip_type_cham",
        "tip_tip_eventtime", "tip_eqpissue", "tip_body_eqp_status", "tip_cham_eqp_status", "tip_eqpissuetime", "tip_eqpline",
    ]

    tip_specific = tip_filtered[
        (tip_filtered["process"] != "-") & (tip_filtered["step"] != "-") & (tip_filtered["ppid"] != "-")
    ].copy()
    print(f"[축약 점검] exact tip 축약 전 rows(필터 후): {len(tip_specific)}")
    exact_dedup_start = time.perf_counter()
    tip_specific["tip_eventtime_dt"] = safe_to_datetime(tip_specific["tip_tip_eventtime"])
    tip_specific["eqpissuetime_dt"] = safe_to_datetime(tip_specific["tip_eqpissuetime"])
    exact_tip_keys = ["process", "step", "eqpid", "ppid", "tip_eqpcham", "tip_chamberid"]
    if tip_specific["tip_eventtime_dt"].notna().any() or tip_specific["eqpissuetime_dt"].notna().any():
        tip_specific = tip_specific.sort_values(["tip_eventtime_dt", "eqpissuetime_dt"]).drop_duplicates(
            exact_tip_keys, keep="last"
        )
    else:
        tip_specific = tip_specific.drop_duplicates(exact_tip_keys, keep="last")
    tip_specific = tip_specific.drop(columns=["tip_eventtime_dt", "eqpissuetime_dt"])
    exact_dedup_elapsed = time.perf_counter() - exact_dedup_start
    print(f"[축약 점검] exact tip 축약 후 rows(필터 후): {len(tip_specific)}")
    print(f"[시간] exact tip 축약: {exact_dedup_elapsed:.1f}초")
    if len(tip_specific) > len(tip) * 0.95:
        print("[경고] exact tip 축약 전 rows(필터 후)가 원본 tip rows와 거의 같습니다. 필터 조건을 확인하세요.")
    before_rows = len(me)
    print(f"[행수 점검] exact tip 조인 전 rows: {before_rows}")
    exact_join_start = time.perf_counter()
    met = me.merge(
        tip_specific,
        left_on=["proc_id", "step_seq", "eqp_id", "recipe_id"],
        right_on=["process", "step", "eqpid", "ppid"],
        how="left",
    )
    after_rows = len(met)
    exact_join_elapsed = time.perf_counter() - exact_join_start
    print(f"[행수 점검] exact tip 조인 후 rows: {after_rows}")
    print(f"[시간] exact tip 조인: {exact_join_elapsed:.1f}초")
    if after_rows > before_rows:
        print("[안내] exact tip 조인으로 rows가 증가했습니다. tip_eqpcham/tip_chamberid 차이로 인한 증가인지 점검합니다.")
    exact_full_dup = int(met.duplicated(keep=False).sum())
    print(f"[중복 보정] exact tip 조인 후 전체 컬럼 완전중복 rows: {exact_full_dup}")
    if exact_full_dup:
        before_dedup = len(met)
        met = met.drop_duplicates()
        print(f"[중복 보정] exact tip 조인 후 전체 컬럼 기준 drop_duplicates 적용: {before_dedup} -> {len(met)}")

    tip_wild = tip_filtered[
        (tip_filtered["tip_prevent"] == "PREVENT")
        & ((tip_filtered["process"] == "-") | (tip_filtered["step"] == "-") | (tip_filtered["ppid"] == "-"))
    ].copy()
    tip_wild["specificity"] = (
        (tip_wild["process"] != "-").astype(int) + (tip_wild["step"] != "-").astype(int) + (tip_wild["ppid"] != "-").astype(int)
    )
    tip_wild["tip_eventtime_dt"] = safe_to_datetime(tip_wild["tip_tip_eventtime"])
    tip_wild["eqpissuetime_dt"] = safe_to_datetime(tip_wild["tip_eqpissuetime"])
    tip_wild = tip_wild.reset_index(drop=True)
    tip_wild["_wild_order"] = tip_wild.index

    wild_start = time.perf_counter()
    met = met.reset_index(drop=True)
    met["_row_id"] = met.index
    candidates: list[pd.DataFrame] = []
    for _, r in tip_wild.iterrows():
        mask = met["eqp_id"].eq(r["eqpid"])
        if r["process"] != "-":
            mask &= met["proc_id"].eq(r["process"])
        if r["step"] != "-":
            mask &= met["step_seq"].eq(r["step"])
        if r["ppid"] != "-":
            mask &= met["recipe_id"].eq(r["ppid"])
        matched = met.loc[mask, ["_row_id"]].copy()
        if matched.empty:
            continue
        for c in tip_cols + ["specificity", "tip_eventtime_dt", "eqpissuetime_dt", "_wild_order"]:
            matched[c] = r.get(c)
        candidates.append(matched)

    if candidates:
        wild_match = pd.concat(candidates, ignore_index=True)
        wild_match = wild_match.sort_values(["_row_id", "specificity", "tip_eventtime_dt", "eqpissuetime_dt", "_wild_order"])
        wild_best = wild_match.drop_duplicates("_row_id", keep="last")
        met = met.merge(wild_best.drop(columns=["specificity", "tip_eventtime_dt", "eqpissuetime_dt", "_wild_order"]), on="_row_id", how="left", suffixes=("", "_wild"))
        for c in tip_cols:
            wc = f"{c}_wild"
            if wc in met.columns:
                met[c] = met[wc].combine_first(met[c])
                met = met.drop(columns=[wc])
    before_rows = len(met)
    after_rows = len(met)
    print(f"[행수 점검] wildcard tip 반영 후 rows: {after_rows}")
    print(f"[중복 점검] wildcard tip 반영 후 전체 컬럼 기준 완전중복 rows: {met.drop(columns=['_row_id']).duplicated(keep=False).sum()}")
    print(f"[시간] wildcard tip 반영: {time.perf_counter() - wild_start:.1f}초")
    if after_rows != before_rows:
        raise WipBuildError(f"wildcard overlay 후 행 수가 변경되었습니다. before={before_rows}, after={after_rows}. wildcard는 overlay로 기존 행을 보존해야 합니다.")

    met["body_eqp_status"] = met["tip_body_eqp_status"].combine_first(met["eqp_body_eqp_status"])
    met["batch_kind"] = met["tip_batch_kind"].combine_first(met["eqp_batch_kind"])
    met["eqpline"] = met["tip_eqpline"].combine_first(met["eqp_eqpline"])
    met["eqpissuetime"] = met["tip_eqpissuetime"].combine_first(met["eqp_body_status_change_time"])

    fallback_issue = met["eqp_body_eqp_status"].where(met["eqp_body_eqp_status"].isin(["LOCAL", "PM", "DOWN"]))
    met["eqpissue"] = met["tip_eqpissue"].combine_first(fallback_issue)

    hold_start = time.perf_counter()
    hold_work = hold.copy()
    hold_work["lot_id"] = hold_work["lot_id"].fillna("").astype(str).str.strip()
    hold_work["step_seq"] = hold_work["step_seq"].fillna("").astype(str).str.strip()
    if "item_type" not in hold_work.columns:
        for c in ["item_type", "hold_user", "hold_reason", "hold_date"]:
            if c not in hold_work.columns:
                hold_work[c] = pd.NA
    hold_work["item_type"] = hold_work["item_type"].fillna("").astype(str).str.strip().str.upper()
    hold_work["category"] = hold_work["item_type"].map({
        "EXCEPTION": "예약제외",
        "HOLD LOT": "hold",
        "FUTUREHOLD": "hold",
        "FTKINPVLOT": "ftp",
    })
    hold_valid = hold_work[hold_work["category"].notna()].copy()
    hold_valid["hold_date"] = safe_to_datetime(hold_valid["hold_date"])

    print(f"[hold 집계 점검] hold raw rows: {len(hold)}")
    print(f"[hold 집계 점검] category 적용 rows: {len(hold_valid)}")

    hold_grouped = hold_valid.groupby(["lot_id", "step_seq", "category"], as_index=False).agg(
        flag=("category", lambda _: "O"),
        user=("hold_user", _unique_join_text),
        reason=("hold_reason", _unique_join_text),
        date=("hold_date", "min"),
    )
    print(f"[hold 집계 점검] grouped lot_id+step_seq+category rows: {len(hold_grouped)}")
    print(f"[시간] hold 집계/merge: {time.perf_counter() - hold_start:.1f}초")

    def build_category_part(category: str, prefix: str) -> pd.DataFrame:
        part = hold_grouped.loc[hold_grouped["category"] == category, ["lot_id", "step_seq", "flag", "user", "reason", "date"]].copy()
        dup = int(part.duplicated(["lot_id", "step_seq"], keep=False).sum())
        if dup:
            raise WipBuildError(f"{prefix} part 생성 중 lot_id+step_seq 중복 {dup}건이 발견되었습니다.")
        return part.rename(columns={
            "flag": prefix,
            "user": f"{prefix}_user",
            "reason": f"{prefix}_reason",
            "date": f"{prefix}_date",
        })

    part_exc = build_category_part("예약제외", "예약제외")
    part_hold = build_category_part("hold", "hold")
    part_ftp = build_category_part("ftp", "ftp")

    hold_summary = part_exc.merge(part_hold, on=["lot_id", "step_seq"], how="outer", validate="one_to_one")
    hold_summary = hold_summary.merge(part_ftp, on=["lot_id", "step_seq"], how="outer", validate="one_to_one")

    dup_hold_summary = int(hold_summary.duplicated(["lot_id", "step_seq"], keep=False).sum())
    print(f"[hold 집계 점검] 최종 hold_summary rows: {len(hold_summary)}")
    print(f"[hold 집계 점검] 최종 hold_summary lot_id+step_seq duplicate rows: {dup_hold_summary}")
    if dup_hold_summary != 0:
        raise WipBuildError(f"hold_summary lot_id+step_seq 중복 rows가 {dup_hold_summary}건입니다.")

    source_categories = hold_valid.groupby(["lot_id", "step_seq"])["category"].apply(set).to_dict()

    def extract_flags(row: pd.Series) -> set[str]:
        flags: set[str] = set()
        if row.get("예약제외") == "O":
            flags.add("예약제외")
        if row.get("hold") == "O":
            flags.add("hold")
        if row.get("ftp") == "O":
            flags.add("ftp")
        return flags

    hold_summary["_result_flags"] = hold_summary.apply(extract_flags, axis=1)
    flag_errors: list[tuple[str, str, set[str], set[str]]] = []
    for _, row in hold_summary[["lot_id", "step_seq", "_result_flags"]].iterrows():
        key = (row["lot_id"], row["step_seq"])
        src = source_categories.get(key, set())
        extra = row["_result_flags"] - src
        if extra:
            flag_errors.append((row["lot_id"], row["step_seq"], src, row["_result_flags"]))

    print(f"[hold flag 점검] source keys: {len(source_categories)}, result keys: {len(hold_summary)}")
    print(f"[hold flag 점검] 원천에 없는 category를 포함한 결과 rows: {len(flag_errors)}")
    if flag_errors:
        samples = flag_errors[:10]
        sample_text = "\n".join(
            f"- lot_id={lot}, step_seq={step}, 원천 category={sorted(src)}, 결과 flag={sorted(dst)}"
            for lot, step, src, dst in samples
        )
        raise WipBuildError(f"hold flag 검증 실패. 원천에 없는 category가 결과에 표시되었습니다.\n샘플(최대 10건):\n{sample_text}")
    hold_summary = hold_summary.drop(columns=["_result_flags"])

    met["lot_id"] = met["lot_id"].fillna("").astype(str).str.strip()
    met["step_seq"] = met["step_seq"].fillna("").astype(str).str.strip()
    hold_summary["lot_id"] = hold_summary["lot_id"].fillna("").astype(str).str.strip()
    hold_summary["step_seq"] = hold_summary["step_seq"].fillna("").astype(str).str.strip()

    left_keys = met[["lot_id", "step_seq"]].drop_duplicates()
    right_keys = hold_summary[["lot_id", "step_seq"]].drop_duplicates()
    overlap = left_keys.merge(right_keys, on=["lot_id", "step_seq"], how="inner").shape[0]
    print(f"[hold merge 점검] met rows: {len(met)}")
    print(f"[hold merge 점검] met unique lot_id+step_seq: {len(left_keys)}")
    print(f"[키 분포 점검] met lot_id+step_seq 중복 rows: {int(met.duplicated(['lot_id', 'step_seq'], keep=False).sum())}")
    print("[안내] met는 lot_id+step_seq 기준 여러 행이 정상일 수 있습니다. tip_eqpcham/tip_chamberid 등 챔버 정보가 다르면 보존합니다.")
    print(f"[hold merge 점검] hold_summary rows: {len(hold_summary)}")
    print(f"[hold merge 점검] hold_summary columns: {hold_summary.columns.tolist()}")
    print(f"[hold merge 점검] hold_summary duplicate key rows: {int(hold_summary.duplicated(['lot_id', 'step_seq'], keep=False).sum())}")
    print(f"[hold merge 점검] key overlap unique count: {overlap}")

    met_before = len(met)
    meth = met.merge(hold_summary, on=["lot_id", "step_seq"], how="left", validate="m:1")
    after_rows = len(meth)
    print(f"[행수 점검] hold merge 후 rows: {after_rows}")
    print(f"[중복 점검] hold merge 후 전체 컬럼 기준 완전중복 rows: {meth.duplicated(keep=False).sum()}")
    if after_rows != met_before:
        raise WipBuildError(f"hold merge 후 행 수가 변경되었습니다. before={met_before}, after={after_rows}. hold 집계/조인 로직을 확인하세요.")
    meth = meth.drop(columns=["_row_id"], errors="ignore")
    print(f"[행수 점검] 최종 wip rows: {len(meth)}")
    chamber_multi_groups = 0
    if {"lot_id", "step_seq", "tip_eqpcham", "tip_chamberid"}.issubset(meth.columns):
        combo_per_key = (
            meth.assign(_ch_key=meth[["tip_eqpcham", "tip_chamberid"]].fillna("").astype(str).agg("|".join, axis=1))
            .groupby(["lot_id", "step_seq"])["_ch_key"].nunique(dropna=False)
        )
        chamber_multi_groups = int((combo_per_key > 1).sum())
    print(f"[중복 점검] 최종 wip 전체 컬럼 기준 완전중복 rows: {meth.duplicated(keep=False).sum()}")
    print(f"[챔버 보존 점검] 같은 lot_id+step_seq 내 tip_eqpcham/tip_chamberid 다중 조합 group 수: {chamber_multi_groups}")
    print("[챔버 보존 점검] 해당 행들은 중복 제거 대상이 아닙니다.")

    return meth




def build_exclusion_type(row: pd.Series) -> str | pd.NA:
    def extract_oldest_datetime(value):
        if is_blank(value):
            return pd.NaT
        text = str(value)
        parts = [p.strip() for p in text.split(",")] if "," in text else [text.strip()]
        candidates = []
        for p in parts:
            dt = _parse_single_datetime(p)
            if pd.notna(dt):
                candidates.append(dt)
        if not candidates:
            dt = _parse_single_datetime(text)
            return dt if pd.notna(dt) else pd.NaT
        return min(candidates)

    def has_value(v) -> bool:
        return not is_blank(v)

    def build_line(label: str, flag_val, user_val, reason_val, date_val, sysdate_val) -> str | None:
        should_create = is_o(flag_val) or has_value(user_val) or has_value(reason_val) or has_value(date_val)
        if not should_create:
            return None

        user_text = _normalize_text(user_val)
        reason_text = _normalize_text(reason_val)
        oldest_dt = extract_oldest_datetime(date_val)
        elapsed_text = format_elapsed_days_label(sysdate_val, oldest_dt)

        parts: list[str] = []
        if user_text:
            parts.append(user_text)
        if reason_text:
            parts.append(reason_text)
        parts.append(elapsed_text)
        detail = "/".join(parts).strip()
        if not detail:
            return None
        return f"{label}: {detail}"

    lines: list[str] = []
    hold_line = build_line("HOLD", row.get("hold"), row.get("hold_user"), row.get("hold_reason"), row.get("hold_date"), row.get("sysdate"))
    ftp_line = build_line("FTP", row.get("ftp"), row.get("ftp_user"), row.get("ftp_reason"), row.get("ftp_date"), row.get("sysdate"))
    except_line = build_line("예약제외", row.get("예약제외"), row.get("예약제외_user"), row.get("예약제외_reason"), row.get("예약제외_date"), row.get("sysdate"))
    for line in [hold_line, ftp_line, except_line]:
        if line:
            lines.append(line)
    return "\n".join(lines) if lines else pd.NA


def _series_nonblank_count(df: pd.DataFrame, col: str) -> int:
    if col not in df.columns:
        return 0
    return int(df[col].map(lambda v: not is_blank(v)).sum())


def _masked_samples(df: pd.DataFrame, col: str, n: int = 3) -> str:
    if col not in df.columns:
        return "-"
    vals = [str(v).strip() for v in df[col] if not is_blank(v)]
    out = []
    for v in vals[:n]:
        out.append(f"len={len(v)} head='{v[:4]}' tail='{v[-4:]}'")
    return ", ".join(out) if out else "-"


def _pattern_counts(df: pd.DataFrame, col: str) -> dict[str, int]:
    if col not in df.columns:
        return {"-": 0, "/": 0, ":": 0, " ": 0, ".": 0}
    vals = [str(v).strip() for v in df[col] if not is_blank(v)]
    return {
        "-": sum("-" in v for v in vals),
        "/": sum("/" in v for v in vals),
        ":": sum(":" in v for v in vals),
        " ": sum(" " in v for v in vals),
        ".": sum("." in v for v in vals),
    }

def build_wip_concat(wip: pd.DataFrame) -> pd.DataFrame:
    concat_start = time.perf_counter()
    group_keys = ["lot_id", "step_seq", "order_seq"]
    missing_keys = [k for k in group_keys if k not in wip.columns]
    if missing_keys:
        raise WipBuildError(f"concat 생성 실패: 그룹 기준 컬럼이 없습니다. 누락={missing_keys}")

    print("[concat 생성] 기준 그룹: lot_id, step_seq, order_seq")
    print(f"[concat 생성] input rows: {len(wip)}")
    work = wip.copy()

    uniqueconcat_cols = [
        "예약제외", "예약제외_user", "예약제외_reason", "예약제외_date",
        "hold", "hold_user", "hold_reason", "hold_date",
        "ftp", "ftp_user", "ftp_reason", "ftp_date",
    ]
    missing_unique_cols = [c for c in uniqueconcat_cols if c not in work.columns]
    if missing_unique_cols:
        print(f"[concat 생성] uniqueconcat 누락 컬럼: {missing_unique_cols}")
    apply_unique_cols = [c for c in uniqueconcat_cols if c in work.columns]

    agg_map = {c: first_valid_value for c in work.columns if c not in group_keys}
    for c in apply_unique_cols:
        agg_map[c] = unique_concat_series
    base = work.groupby(group_keys, dropna=False, as_index=False).agg(agg_map)

    if "eqp_id" in work.columns:
        base["eqpgroup"] = work.groupby(group_keys, dropna=False)["eqp_id"].agg(unique_concat_series).values
    else:
        base["eqpgroup"] = pd.NA
    if "tip_eqpcham" in work.columns:
        base["eqpgroup_cham"] = work.groupby(group_keys, dropna=False)["tip_eqpcham"].agg(unique_concat_series).values
    else:
        base["eqpgroup_cham"] = pd.NA
    eqpgroup_cham_blank_before = int(base["eqpgroup_cham"].map(is_blank).sum())
    fill_mask = base["eqpgroup_cham"].map(is_blank) & ~base["eqpgroup"].map(is_blank)
    replaced_cnt = int(fill_mask.sum())
    base.loc[fill_mask, "eqpgroup_cham"] = base.loc[fill_mask, "eqpgroup"]
    eqpgroup_cham_blank_after = int(base["eqpgroup_cham"].map(is_blank).sum())
    eqpgroup_exists_cham_blank_after = int((~base["eqpgroup"].map(is_blank) & base["eqpgroup_cham"].map(is_blank)).sum())
    print(f"[eqpgroup_cham 보정] 보정 전 blank rows: {eqpgroup_cham_blank_before}")
    print(f"[eqpgroup_cham 보정] eqpgroup으로 대체한 rows: {replaced_cnt}")
    print(f"[eqpgroup_cham 보정] 보정 후 blank rows: {eqpgroup_cham_blank_after}")
    print(f"[eqpgroup_cham 검증] eqpgroup 존재 + eqpgroup_cham blank rows: {eqpgroup_exists_cham_blank_after}")
    eqp_eqpline_exists = "eqp_eqpline" in work.columns
    print(f"[eqpline 점검] output_wip eqp_eqpline 존재: {eqp_eqpline_exists}")
    if not eqp_eqpline_exists:
        raise RuntimeError("output_wip에 eqp_eqpline 컬럼이 없어 output_wip_concat.eqpline을 생성할 수 없습니다.")

    eqp_eqpline_nonblank = int(work["eqp_eqpline"].map(lambda v: not is_blank(v)).sum())
    print(f"[eqpline 점검] output_wip eqp_eqpline non-blank rows: {eqp_eqpline_nonblank}")

    eqpline_by_group = (
        work.groupby(group_keys, dropna=False)["eqp_eqpline"]
        .apply(sorted_unique_concat_series)
        .reset_index(name="eqpline")
    )

    base = base.drop(columns=["eqpline"], errors="ignore")
    base = base.merge(eqpline_by_group, on=group_keys, how="left", validate="one_to_one")

    eqpline_nonblank = int(base["eqpline"].map(lambda v: not is_blank(v)).sum())
    eqpline_blank = int(base["eqpline"].map(is_blank).sum())
    print(f"[eqpline 점검] output_wip_concat eqpline non-blank rows: {eqpline_nonblank}")
    print(f"[eqpline 점검] output_wip_concat eqpline blank rows: {eqpline_blank}")
    if eqp_eqpline_nonblank > 0 and eqpline_blank > 0:
        raise RuntimeError("output_wip_concat.eqpline 생성 오류: output_wip.eqp_eqpline 값이 있는데 최종 eqpline에 빈 값이 발생했습니다.")

    base["투입경과일_일"] = base.apply(lambda r: _elapsed_days_float(r.get("sysdate"), r.get("start_date")), axis=1)
    base["step도착경과_일"] = base.apply(lambda r: calculate_day_diff(r.get("sysdate"), r.get("step_arrive_date")), axis=1)
    base["마지막event경과_일"] = base.apply(lambda r: calculate_day_diff(r.get("sysdate"), r.get("last_event_date")), axis=1)
    print("[concat 경과일] step도착경과_일 / 마지막event경과_일 DAY 단위 계산 완료")

    work["_prevent_item"] = work.apply(make_prevent_item, axis=1)
    prevent_target_mask = (
        work.get("tip_type_body").map(lambda v: normalize_text(v) == "PREVENT")
        | work.get("tip_type_cham").map(lambda v: normalize_text(v) == "PREVENT")
    ) if ("tip_type_body" in work.columns and "tip_type_cham" in work.columns) else pd.Series(False, index=work.index)
    prevent_target = work.loc[prevent_target_mask].copy()
    prevent_total = len(prevent_target)
    print(f"[prevent 진단] 대상 row 수: {prevent_total}")
    prevent_sys_parsed = safe_to_datetime(prevent_target["sysdate"]) if prevent_total and "sysdate" in prevent_target.columns else pd.Series(dtype="datetime64[ns]")
    print(f"[prevent 진단] sysdate 파싱 성공: {int(prevent_sys_parsed.notna().sum())} / {prevent_total}")
    tip_event_col_exists = "tip_tip_eventtime" in prevent_target.columns
    print(f"[prevent 진단] tip_tip_eventtime 컬럼 존재: {tip_event_col_exists}")
    if tip_event_col_exists and prevent_total:
        tip_event_nonblank = int(prevent_target["tip_tip_eventtime"].map(lambda v: not is_blank(v)).sum())
        tip_event_parsed = safe_to_datetime(prevent_target["tip_tip_eventtime"])
        print(f"[prevent 진단] tip_tip_eventtime non-blank: {tip_event_nonblank} / {prevent_total}")
        print(f"[prevent 진단] tip_tip_eventtime 파싱 성공: {int(tip_event_parsed.notna().sum())} / {prevent_total}")
    elif prevent_total:
        print(f"[prevent 진단] tip_tip_eventtime non-blank: 0 / {prevent_total}")
        print(f"[prevent 진단] tip_tip_eventtime 파싱 성공: 0 / {prevent_total}")
    prevent_items = (
        work.groupby(group_keys, dropna=False)["_prevent_item"]
        .apply(lambda s: ", ".join(sorted(set([_normalize_text(v) for v in s if _normalize_text(v)]))) if any(_normalize_text(v) for v in s) else pd.NA)
    )
    base["prevent"] = prevent_items.values
    base["prevent"] = base["prevent"].apply(lambda x: pd.NA if pd.isna(x) else f"PREVENT: {x}")
    prevent_fail_items = int(base["prevent"].astype("string").str.count("경과일계산불가").fillna(0).sum())
    prevent_target_items = int(base["prevent"].astype("string").str.count(r"\(").fillna(0).sum())
    print(f"[prevent 진단] 경과일계산불가 item 수: {prevent_fail_items}")
    if prevent_target_items > 0 and prevent_fail_items == prevent_target_items:
        print("[prevent 경고] 대상 item이 있으나 경과일계산불가가 전부입니다.")
    print("[concat 검증] prevent tip_tip_eventtime 기준 경과일 계산 완료")

    issue_candidate_cols = ["eqpissuetime", "tip_eqpissuetime", "tip_tip_eventtime", "eqp_body_status_change_time", "body_status_change_time", "body_status_change_time_eqp"]

    issue_target_mask = (
        work.get("tip_eqpissue").map(lambda v: not is_blank(v)) if "tip_eqpissue" in work.columns else pd.Series(False, index=work.index)
    ) | (
        work.get("eqpissue").map(lambda v: not is_blank(v)) if "eqpissue" in work.columns else pd.Series(False, index=work.index)
    ) | (
        work.get("body_eqp_status").map(is_bad_status) if "body_eqp_status" in work.columns else pd.Series(False, index=work.index)
    ) | (
        work.get("tip_body_eqp_status").map(is_bad_status) if "tip_body_eqp_status" in work.columns else pd.Series(False, index=work.index)
    ) | (
        work.get("tip_cham_eqp_status").map(is_bad_status) if "tip_cham_eqp_status" in work.columns else pd.Series(False, index=work.index)
    )
    issue_target = work.loc[issue_target_mask].copy()
    total_issue_target = len(issue_target)
    print(f"[issue_eqp 진단] 대상 row 수: {total_issue_target}")
    issue_target["_sysdate_dt"] = safe_to_datetime(issue_target.get("sysdate")) if total_issue_target else pd.Series(dtype="datetime64[ns]")
    print(f"[issue_eqp 진단] sysdate 파싱 성공: {int(issue_target['_sysdate_dt'].notna().sum())} / {total_issue_target}")
    print(f"[issue_eqp 진단] eqpissuetime 후보 컬럼 존재 여부: { {c:(c in issue_target.columns) for c in ['eqpissuetime','tip_eqpissuetime']} }")
    print(f"[issue_eqp 진단] eqp_body_status_change_time 후보 존재 여부: { {c:(c in issue_target.columns) for c in ['eqp_body_status_change_time','body_status_change_time','body_status_change_time_eqp']} }")

    for c in issue_candidate_cols:
        print(f"[issue_eqp 진단] {c} non-blank: {_series_nonblank_count(issue_target, c)} / {total_issue_target}")
        if c in issue_target.columns:
            lengths = issue_target[c].map(lambda v: len(str(v).strip()) if not is_blank(v) else pd.NA).dropna().astype(int)
            print(f"[issue_eqp 진단] {c} 길이분포 top5: {lengths.value_counts().head(5).to_dict()}")
            pat = _pattern_counts(issue_target, c)
            print(f"[issue_eqp 진단] {c} pattern count: -= {pat['-']}, /= {pat['/']}, := {pat[':']}, space= {pat[' ']}, .= {pat['.']}")
            print(f"[issue_eqp 진단] {c} masked samples: {_masked_samples(issue_target, c)}")

    eqp_primary = safe_to_datetime(issue_target["eqpissuetime"]) if "eqpissuetime" in issue_target.columns else pd.Series(pd.NaT, index=issue_target.index)
    eqp_fallback = safe_to_datetime(issue_target["tip_eqpissuetime"]) if "tip_eqpissuetime" in issue_target.columns else pd.Series(pd.NaT, index=issue_target.index)
    body_primary = safe_to_datetime(issue_target["eqp_body_status_change_time"]) if "eqp_body_status_change_time" in issue_target.columns else pd.Series(pd.NaT, index=issue_target.index)
    body_fb1 = safe_to_datetime(issue_target["body_status_change_time"]) if "body_status_change_time" in issue_target.columns else pd.Series(pd.NaT, index=issue_target.index)
    body_fb2 = safe_to_datetime(issue_target["body_status_change_time_eqp"]) if "body_status_change_time_eqp" in issue_target.columns else pd.Series(pd.NaT, index=issue_target.index)

    issue_target["_issue_a"] = eqp_primary.combine_first(eqp_fallback)
    issue_target["_issue_b"] = body_primary.combine_first(body_fb1).combine_first(body_fb2)
    issue_target["_issue_ref"] = issue_target[["_issue_a", "_issue_b"]].min(axis=1)

    print(f"[issue_eqp 진단] eqpissuetime primary 사용 가능 rows: {int(eqp_primary.notna().sum())}")
    print(f"[issue_eqp 진단] tip_eqpissuetime fallback 사용 rows: {int((eqp_primary.isna() & eqp_fallback.notna()).sum())}")
    print(f"[issue_eqp 진단] eqp_body_status_change_time primary 사용 가능 rows: {int(body_primary.notna().sum())}")
    print(f"[issue_eqp 진단] body_status_change_time fallback 사용 rows: {int((body_primary.isna() & body_fb1.notna()).sum())}")

    ref_ok = int(issue_target["_issue_ref"].notna().sum()) if total_issue_target else 0
    issue_fail = int((issue_target["_sysdate_dt"].isna() | issue_target["_issue_ref"].isna()).sum()) if total_issue_target else 0
    print(f"[issue_eqp 진단] 기준일 계산 성공: {ref_ok} / {total_issue_target}")
    print(f"[issue_eqp 진단] 경과일계산불가 item 수: {issue_fail}")
    if total_issue_target and ref_ok == 0:
        print("[issue_eqp 경고] 기준일 최종 성공 rows가 0입니다. 원천 시간값 또는 포맷을 확인하세요.")

    work["eqpissuetime"] = safe_to_datetime(work["eqpissuetime"]).combine_first(safe_to_datetime(work["tip_eqpissuetime"]) if "tip_eqpissuetime" in work.columns else pd.Series(pd.NaT, index=work.index)) if "eqpissuetime" in work.columns else (safe_to_datetime(work["tip_eqpissuetime"]) if "tip_eqpissuetime" in work.columns else pd.Series(pd.NaT, index=work.index))
    body_base = safe_to_datetime(work["eqp_body_status_change_time"]) if "eqp_body_status_change_time" in work.columns else pd.Series(pd.NaT, index=work.index)
    if "body_status_change_time" in work.columns:
        body_base = body_base.combine_first(safe_to_datetime(work["body_status_change_time"]))
    if "body_status_change_time_eqp" in work.columns:
        body_base = body_base.combine_first(safe_to_datetime(work["body_status_change_time_eqp"]))
    work["eqp_body_status_change_time"] = body_base

    issue_group = {k: [] for k in ["DOWN", "PM", "LOCAL"]}
    for _, grp in work.groupby(group_keys, dropna=False):
        state_map = {k: [] for k in ["DOWN", "PM", "LOCAL"]}
        seen = {k: set() for k in ["DOWN", "PM", "LOCAL"]}
        for _, row in grp.iterrows():
            items = make_issue_items(row)
            for st in ["DOWN", "PM", "LOCAL"]:
                for item in items[st]:
                    if item not in seen[st]:
                        seen[st].add(item)
                        state_map[st].append(item)
        for st in ["DOWN", "PM", "LOCAL"]:
            state_map[st] = sorted(set(state_map[st]), key=lambda x: x.split("(", 1)[0])
        parts = [f"{st}: {', '.join(state_map[st])}" for st in ["DOWN", "PM", "LOCAL"] if state_map[st]]
        issue_group["DOWN"].append(parts)
    issue_values = []
    for parts in issue_group["DOWN"]:
        issue_values.append(" / ".join(parts) if parts else pd.NA)
    base["issue_eqp"] = issue_values
    issue_fail_items = int(base["issue_eqp"].astype("string").str.count("경과일계산불가").fillna(0).sum())
    issue_target_items = int(base["issue_eqp"].astype("string").str.count(r"\(").fillna(0).sum())
    if issue_target_items > 0 and issue_fail_items == issue_target_items:
        print("[issue_eqp 경고] 대상 item이 있으나 경과일계산불가가 전부입니다.")
    print("[concat 검증] issue_eqp 기준일 min(eqpissuetime, eqp_body_status_change_time) 계산 완료")

    base = apply_wait_blocked_status(base, work, group_keys)

    for cat, flag_col, date_col in [("HOLD", "hold", "hold_date"), ("FTP", "ftp", "ftp_date"), ("예약제외", "예약제외", "예약제외_date")]:
        target_rows = int(base[flag_col].map(is_o).sum()) if flag_col in base.columns else 0
        non_blank = int(base[date_col].map(lambda v: not is_blank(v)).sum()) if date_col in base.columns else 0
        parsed = safe_to_datetime(base[date_col]) if date_col in base.columns else pd.Series(dtype="datetime64[ns]")
        parsed_cnt = int(parsed.notna().sum()) if len(parsed) else 0
        print(f"[exclusion_type 진단] {cat} 대상 rows: {target_rows}")
        print(f"[exclusion_type 진단] {cat} {date_col} non-blank: {non_blank}")
        print(f"[exclusion_type 진단] {cat} {date_col} 파싱 성공: {parsed_cnt}")
    base["exclusion_type"] = base.apply(build_exclusion_type, axis=1)
    if "exclusion_type" not in base.columns:
        raise RuntimeError("exclusion_type 생성에 실패했습니다.")
    non_empty_exclusion = int(base["exclusion_type"].map(lambda v: not is_blank(v)).sum())
    print("[concat 컬럼정리] exclusion_type 생성 완료")
    print(f"[concat 컬럼정리] exclusion_type non-empty rows: {non_empty_exclusion} / {len(base)}")
    hold_line_cnt = int(base["exclusion_type"].astype(str).str.contains(r"(^|\n)HOLD:\s*\S", regex=True, na=False).sum())
    ftp_line_cnt = int(base["exclusion_type"].astype(str).str.contains(r"(^|\n)FTP:\s*\S", regex=True, na=False).sum())
    exc_line_cnt = int(base["exclusion_type"].astype(str).str.contains(r"(^|\n)예약제외:\s*\S", regex=True, na=False).sum())
    elapsed_fail_cnt = int(base["exclusion_type"].astype(str).str.contains("경과일계산불가", regex=False, na=False).sum())
    print(f"[exclusion_type 진단] HOLD 라인 생성 rows: {hold_line_cnt}")
    print(f"[exclusion_type 진단] FTP 라인 생성 rows: {ftp_line_cnt}")
    print(f"[exclusion_type 진단] 예약제외 라인 생성 rows: {exc_line_cnt}")
    print(f"[exclusion_type 진단] 경과일계산불가 포함 rows: {elapsed_fail_cnt}")
    exclusion_target_rows = int(base[["hold", "ftp", "예약제외"]].apply(lambda r: any(is_o(v) for v in r), axis=1).sum()) if all(c in base.columns for c in ["hold", "ftp", "예약제외"]) else 0
    if exclusion_target_rows > 0 and elapsed_fail_cnt == exclusion_target_rows:
        print("[exclusion_type 경고] 대상 rows가 있으나 경과일계산불가 포함 rows가 전부입니다.")

    # exclusion_type 형식 검증(경고 로그)
    if "exclusion_type" not in base.columns:
        raise WipBuildError("exclusion_type 컬럼이 없습니다.")
    ex_ser = base["exclusion_type"].dropna().astype(str).str.strip()
    simple_only_mask = ex_ser.isin(["HOLD", "FTP", "예약제외"])
    if simple_only_mask.any():
        print(f"[exclusion_type 검증 경고] 단순 키워드만 존재 rows: {int(simple_only_mask.sum())}")
    detail_missing_cnt = 0
    for txt in ex_ser:
        for line in [ln.strip() for ln in txt.split("\n") if ln.strip()]:
            if line.startswith(("HOLD:", "FTP:", "예약제외:")):
                tail = line.split(":", 1)[1].strip() if ":" in line else ""
                if not tail:
                    detail_missing_cnt += 1
    if detail_missing_cnt > 0:
        print(f"[exclusion_type 검증 경고] 라벨 뒤 상세누락 line 수: {detail_missing_cnt}")
    day_token_cnt = int(ex_ser.str.contains("일↑", regex=False).sum())
    calc_fail_token_cnt = int(ex_ser.str.contains("경과일계산불가", regex=False).sum())
    print(f"[exclusion_type 검증] 일↑ 포함 rows: {day_token_cnt}")
    print(f"[exclusion_type 검증] 경과일계산불가 포함 rows: {calc_fail_token_cnt}")
    src_has_exclusion = any(c in base.columns and base[c].map(lambda v: not is_blank(v)).any() for c in ["예약제외", "hold", "ftp"])
    if src_has_exclusion and non_empty_exclusion == 0:
        print("[concat 컬럼정리 경고] 원천 HOLD/FTP/예약제외 데이터가 있으나 exclusion_type이 모두 비어 있습니다.")

    drop_cols = [
        "eqp_id", "tip_eqpcham", "tip_chamberid", "body_eqp_status", "eqpgroup_raw", "ppid", "process", "step",
        "tip_prevent", "tip_type_body", "tip_type_cham", "tip_tip_eventtime", "tip_eqpissue", "tip_body_eqp_status",
        "tip_cham_eqp_status", "tip_eqpissuetime", "tip_eqpline", "tip_batch_kind", "tip_chamber",
        "eqpissuetime", "eqp_group_raw", "eqpgroup_raw", "eqp_body_status_change_time",
    ]
    removed = [c for c in drop_cols if c in base.columns]
    base = base.drop(columns=removed, errors="ignore")
    print(f"[concat 생성] 제거 컬럼: {removed}")
    print("[concat 컬럼정리] eqpissuetime / eqp_group_raw 제거 완료")
    print(f"[concat 생성] uniqueconcat 처리 컬럼: {apply_unique_cols}")

    base = enforce_final_concat_columns(base)
    if "status_reason" in base.columns and "status" in base.columns:
        cols = list(base.columns)
        cols.remove("status_reason")
        status_idx = cols.index("status")
        cols.insert(status_idx + 1, "status_reason")
        base = base[cols]
        print("[concat 컬럼정리] status_reason 위치 조정 완료")

    banned_cols = ["step도착경과_시", "마지막event경과_시", "마지막EVENT경과_시", "eqpissuetime", "eqp_group_raw", "eqpgroup_raw", "eqp_body_status_change_time", "tip_tip_eventtime"]
    remained_banned = [c for c in banned_cols if c in base.columns]
    if remained_banned:
        raise WipBuildError(f"concat 금지 컬럼이 남아 있습니다: {remained_banned}")
    if "step도착경과_일" not in base.columns or "마지막event경과_일" not in base.columns:
        raise WipBuildError("concat 경과일 컬럼 누락: step도착경과_일 또는 마지막event경과_일")

    label_pattern = r"^[^()]+\((\d+\.\d일↑|경과일계산불가)\)$"
    if "prevent" in base.columns:
        p = base["prevent"].dropna().astype(str).str.replace("PREVENT: ", "", regex=False).str.split(", ")
        invalid = p.apply(lambda arr: any(pd.notna(x) and not re.match(label_pattern, x) for x in arr)).any()
        if invalid:
            raise WipBuildError("prevent 형식 오류: 설비명(숫자.숫자일↑) 또는 설비명(경과일계산불가) 형식이어야 합니다.")
    if "issue_eqp" in base.columns:
        tokens = base["issue_eqp"].dropna().astype(str).str.replace(r"(DOWN|PM|LOCAL):\s*", "", regex=True).str.replace(" / ", ", ")
        invalid_issue = tokens.str.split(", ").apply(lambda arr: any(pd.notna(x) and not re.match(label_pattern, x) for x in arr)).any()
        if invalid_issue:
            raise WipBuildError("issue_eqp 형식 오류: 설비명(숫자.숫자일↑) 또는 설비명(경과일계산불가) 형식이어야 합니다.")
    if "exclusion_type" in base.columns:
        ex_tokens_ok = base["exclusion_type"].dropna().astype(str).apply(
            lambda txt: all(
                ("일↑" in line or "경과일계산불가" in line)
                for line in [ln.strip() for ln in txt.split("\n") if ln.strip().startswith(("HOLD:", "FTP:", "예약제외:"))]
            )
        ).all()
        if not ex_tokens_ok:
            raise WipBuildError("exclusion_type 형식 오류: HOLD/FTP/예약제외 라인에 경과일 또는 경과일계산불가가 필요합니다.")
    if "status_reason" in base.columns and "status" in base.columns:
        if list(base.columns).index("status_reason") != list(base.columns).index("status") + 1:
            raise WipBuildError("status_reason 위치 오류: status 바로 오른쪽에 있어야 합니다.")

    expected_rows = wip[group_keys].drop_duplicates().shape[0]
    if len(base) != expected_rows:
        raise WipBuildError(f"concat row 수 불일치: output={len(base)}, expected={expected_rows}")
    if "prevent" in base.columns and base["prevent"].astype(str).str.strip().eq("PREVENT:").any():
        raise WipBuildError("prevent 컬럼에 'PREVENT:'만 존재하는 값이 있습니다.")
    if "issue_eqp" in base.columns:
        bad_issue = base["issue_eqp"].astype(str).str.contains(r"^(DOWN:|PM:|LOCAL:)\s*$", regex=True, na=False)
        if bad_issue.any():
            raise WipBuildError("issue_eqp 컬럼에 빈 라벨만 존재하는 값이 있습니다.")
    remained = [c for c in drop_cols if c in base.columns]
    if remained:
        raise WipBuildError(f"concat 제거 대상 컬럼이 남아 있습니다: {remained}")

    print(f"[concat 생성] output rows: {len(base)}")
    print(f"[시간] concat 생성: {time.perf_counter() - concat_start:.1f}초")
    return base



def enforce_final_concat_columns(df: pd.DataFrame) -> pd.DataFrame:
    before_cols = list(df.columns)
    print(f"[concat 최종컬럼] allowlist 적용 전 columns={len(before_cols)}")

    missing_required = [c for c in FINAL_REQUIRED_CONCAT_COLUMNS if c not in df.columns]
    if missing_required:
        raise RuntimeError(f"concat 최종컬럼 필수 컬럼이 누락되었습니다: {missing_required}")

    allowed_existing = [c for c in FINAL_CONCAT_COLUMNS if c in df.columns]
    dropped_cols = [c for c in before_cols if c not in FINAL_CONCAT_COLUMNS]
    out = df[allowed_existing].copy()

    print(f"[concat 최종컬럼] allowlist 적용 후 columns={len(out.columns)}")
    print(f"[concat 최종컬럼] 제거된 컬럼 수={len(dropped_cols)}")
    if dropped_cols:
        print(f"[concat 최종컬럼] 제거된 컬럼 예시={dropped_cols[:30]}")

    remained_outside = [c for c in out.columns if c not in FINAL_CONCAT_COLUMNS]
    if remained_outside:
        raise RuntimeError(f"concat 최종컬럼 검증 실패: allowlist 외 컬럼이 남아 있습니다: {remained_outside}")

    forbidden_exclusion_parts = [
        "예약제외", "예약제외_user", "예약제외_reason", "예약제외_date",
        "hold", "hold_user", "hold_reason", "hold_date",
        "ftp", "ftp_user", "ftp_reason", "ftp_date", "hold_info",
        "eqp_eqpline", "eqline",
    ]
    still_forbidden = [c for c in forbidden_exclusion_parts if c in out.columns]
    if still_forbidden:
        raise RuntimeError(f"concat 최종컬럼 검증 실패: 제거되어야 할 컬럼이 남아 있습니다: {still_forbidden}")

    print("[concat 최종컬럼] 최종 컬럼 검증 완료")
    return out

def main() -> None:
    script_dir = Path(__file__).resolve().parent
    paths = {
        "eqp": Path(EQP_PATH),
        "hold": Path(HOLD_PATH),
        "mclot": Path(MCLOT_PATH),
        "steppath": Path(STEPPATH_PATH),
        "tip": Path(TIP_PATH),
    }

    mclot, mclot_meta = read_input_csv("mclot", paths["mclot"])
    steppath, steppath_meta = read_input_csv("steppath", paths["steppath"])
    eqp, eqp_meta = read_input_csv("eqpmaster", paths["eqp"])
    tip, tip_meta = read_input_csv("tip", paths["tip"])
    hold, hold_meta = read_input_csv("hold", paths["hold"])
    mcpath = build_mcpath_from_raw_raw(mclot, steppath)
    _assert_required_columns(mcpath, "mcpath")

    wip = build_wip(mcpath, eqp, tip, hold)
    print(f"[wip 상세] 내부 상세 rows: {len(wip)}")
    dup_cnt = int(wip.duplicated().sum())
    if dup_cnt > 0:
        print(f"[경고] 최종 wip 완전중복 rows가 {dup_cnt}건입니다. duplicate_debug 파일을 저장합니다.")
        debug_path = next_available_path(script_dir / "duplicate_debug.xlsx")
        wip.loc[wip.duplicated(keep=False)].to_excel(debug_path, index=False)
        print(f"[중복 디버그] 저장 완료: {debug_path}")
        before = len(wip)
        wip = wip.drop_duplicates()
        print(f"[중복 보정] 원인 축약 후에도 완전중복 {before - len(wip)}건이 남아 최종 저장 전 drop_duplicates로 제거했습니다.")

    wip_concat = build_wip_concat(wip)
    wip_concat = enforce_final_concat_columns(wip_concat)
    if "lot_inform" not in wip_concat.columns:
        raise WipBuildError("최종 output_wip_concat에 lot_inform 컬럼이 없습니다.")
    if wip_concat.columns.get_loc("lot_inform") != wip_concat.columns.get_loc("lot_id") - 1:
        raise WipBuildError("lot_inform은 lot_id 바로 왼쪽에 위치해야 합니다.")
    print(f"[검증] lot_inform non-empty rows: {int(wip_concat['lot_inform'].map(lambda v: not is_blank(v)).sum())}")
    output_concat_path = next_available_path(script_dir / "output_wip_concat.xlsx")
    with pd.ExcelWriter(output_concat_path, engine="openpyxl") as writer:
        wip_concat.to_excel(writer, index=False)
    print(f"[concat 저장 완료] 경로: {output_concat_path}")
    print("[concat 저장 완료] output_wip_concat.xlsx 저장이 완료되었습니다. 이후 DB 적재를 수행합니다.")
    db_df, loaded_at, loaded_id = add_load_metadata(wip_concat)
    print(f"[DB 적재] loaded_at: {loaded_at}")
    print(f"[DB 적재] loaded_id: {loaded_id}")
    print(f"[DB 적재] DB 적재용 columns: {len(db_df.columns)}")

    if "loaded_at" not in db_df.columns:
        raise WipBuildError("DB 적재 검증 실패: loaded_at 컬럼이 없습니다.")
    if "loaded_id" not in db_df.columns:
        raise WipBuildError("DB 적재 검증 실패: loaded_id 컬럼이 없습니다.")
    if db_df["loaded_at"].nunique(dropna=False) != 1:
        raise WipBuildError("DB 적재 검증 실패: loaded_at 값이 실행 내에서 단일값이 아닙니다.")
    if db_df["loaded_id"].nunique(dropna=False) != 1:
        raise WipBuildError("DB 적재 검증 실패: loaded_id 값이 실행 내에서 단일값이 아닙니다.")
    if is_blank(db_df["loaded_id"].iloc[0] if len(db_df) > 0 else loaded_id):
        raise WipBuildError("DB 적재 검증 실패: loaded_id가 비어 있습니다.")

    dataframe_to_mysql_replace(db_df, "wip_report_lotpath")

    print("[입력 파일 요약]")
    for name, meta in [("eqp", eqp_meta), ("hold", hold_meta), ("tip", tip_meta), ("mclot", mclot_meta), ("steppath", steppath_meta)]:
        print(f"- {name} path: {meta['path']}")
        print(f"  size={meta['size']} bytes, rows={meta['rows']}, cols={meta['cols']}, encoding={meta['encoding']}, sep={meta['separator']}")

    print(f"[wip] row={len(wip)}, col={len(wip.columns)}")
    print(f"[결과 요약] output_wip_concat rows: {len(wip_concat)}")


if __name__ == "__main__":
    try:
        main()
    except WipBuildError as exc:
        print(f"오류: {exc}")
        raise SystemExit(1)
