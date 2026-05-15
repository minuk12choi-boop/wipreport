from __future__ import annotations

from pathlib import Path
import re

import pandas as pd



EQP_PATH = r"C:\Users\minuk12.choi\Documents\zhbm_eqpmaster.csv"
HOLD_PATH = r"C:\Users\minuk12.choi\Documents\zhbm_hold.csv"
MCPATH_PATH = r"C:\Users\minuk12.choi\Documents\zhbm_mclotsteppath.csv"
TIP_PATH = r"C:\Users\minuk12.choi\Documents\zhbm_tip.csv"

REQUIRED_COLUMNS = {
    "mcpath": [
        "lot_id",
        "order_seq",
        "step_seq",
        "proc_id",
        "eqp_id",
        "recipe_id",
        "status",
    ],
    "eqp": ["eqp_id", "batch_kind", "eqpline", "body_eqp_status", "body_status_change_time"],
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
    "hold": ["item_type", "lot_id", "step_seq", "hold_user", "hold_reason", "hold_date"],
}

ENCODING_CANDIDATES = ["utf-16", "utf-16-le", "utf-8-sig", "cp949", "euc-kr", "utf-8"]
SEP_CANDIDATES = [",", "\t", "|", ";"]
KEEP_STATUS_REASON = True

FINAL_CONCAT_COLUMNS = [
    "sys_line_id", "cur_line_id", "eqpline", "sysdate", "lot_id", "status", "status_reason", "grade",
    "lot_type", "lot_level", "cur_qty", "carr_id", "bay_name", "proc_id", "order_seq", "sample_step_type",
    "metal_status", "layer_id", "step_level", "연속", "step_seq", "step_desc", "recipe_id", "tkintype",
    "batch_kind", "eqp_type", "eqpgroup", "eqpgroup_cham", "prevent", "issue_eqp", "투입경과일_일",
    "step도착경과_일", "마지막event경과_일", "start_date", "last_tkout_date", "step_arrive_date", "last_event_date",
    "exclusion_type",
]
FINAL_REQUIRED_CONCAT_COLUMNS = ["lot_id", "step_seq", "order_seq", "status", "eqpgroup", "eqpgroup_cham", "prevent", "issue_eqp", "exclusion_type"]


class WipBuildError(Exception):
    pass


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    return df


def _assert_required_columns(df: pd.DataFrame, name: str) -> None:
    missing = [c for c in REQUIRED_COLUMNS[name] if c not in df.columns]
    if missing:
        raise WipBuildError(f"필수 컬럼 누락: {name}에 {', '.join(missing)} 컬럼이 없습니다.")


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


def safe_to_datetime(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce")


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


def build_wip(mcpath: pd.DataFrame, eqp: pd.DataFrame, tip: pd.DataFrame, hold: pd.DataFrame) -> pd.DataFrame:
    print(f"[행수 점검] mcpath 원본: {len(mcpath)}")
    print(f"[행수 점검] eqp 원본: {len(eqp)}")
    print(f"[행수 점검] tip 원본: {len(tip)}")
    print(f"[행수 점검] hold 원본: {len(hold)}")
    log_duplicate_keys(eqp, ["eqp_id"], "eqp 조인 키")
    log_duplicate_keys(tip, ["process", "step", "eqpid", "ppid", "eqpcham", "chamberid"], "exact tip 조인 키(챔버 포함)")
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

    tip_cols = [
        "tip_eqpcham", "tip_chamberid", "tip_batch_kind", "tip_prevent", "tip_type_body", "tip_type_cham",
        "tip_tip_eventtime", "tip_eqpissue", "tip_body_eqp_status", "tip_cham_eqp_status", "tip_eqpissuetime", "tip_eqpline",
    ]

    tip_specific = tip_renamed[
        (tip_renamed["process"] != "-") & (tip_renamed["step"] != "-") & (tip_renamed["ppid"] != "-")
    ].copy()
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
    print(f"[축약 점검] exact tip 축약 후 rows: {len(tip_specific)}")
    before_rows = len(me)
    print(f"[행수 점검] exact tip 조인 전 rows: {before_rows}")
    met = me.merge(
        tip_specific,
        left_on=["proc_id", "step_seq", "eqp_id", "recipe_id"],
        right_on=["process", "step", "eqpid", "ppid"],
        how="left",
    )
    after_rows = len(met)
    print(f"[행수 점검] exact tip 조인 후 rows: {after_rows}")
    if after_rows > before_rows:
        print("[안내] exact tip 조인으로 rows가 증가했습니다. tip_eqpcham/tip_chamberid 차이로 인한 증가인지 점검합니다.")
    exact_full_dup = int(met.duplicated(keep=False).sum())
    print(f"[중복 점검] exact tip 조인 후 전체 컬럼 기준 완전중복 rows: {exact_full_dup}")
    if exact_full_dup:
        raise WipBuildError(f"exact tip 조인 후 전체 컬럼 기준 완전중복 rows가 {exact_full_dup}건입니다.")

    tip_wild = tip_renamed[
        (tip_renamed["tip_prevent"] == "PREVENT")
        & ((tip_renamed["process"] == "-") | (tip_renamed["step"] == "-") | (tip_renamed["ppid"] == "-"))
    ].copy()
    tip_wild["specificity"] = (
        (tip_wild["process"] != "-").astype(int) + (tip_wild["step"] != "-").astype(int) + (tip_wild["ppid"] != "-").astype(int)
    )
    tip_wild["tip_eventtime_dt"] = safe_to_datetime(tip_wild["tip_tip_eventtime"])
    tip_wild["eqpissuetime_dt"] = safe_to_datetime(tip_wild["tip_eqpissuetime"])
    tip_wild = tip_wild.reset_index(drop=True)
    tip_wild["_wild_order"] = tip_wild.index

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
    if after_rows != before_rows:
        raise WipBuildError(f"wildcard overlay 후 행 수가 변경되었습니다. before={before_rows}, after={after_rows}. wildcard는 overlay로 기존 행을 보존해야 합니다.")

    met["body_eqp_status"] = met["tip_body_eqp_status"].combine_first(met["eqp_body_eqp_status"])
    met["batch_kind"] = met["tip_batch_kind"].combine_first(met["eqp_batch_kind"])
    met["eqpline"] = met["tip_eqpline"].combine_first(met["eqp_eqpline"])
    met["eqpissuetime"] = met["tip_eqpissuetime"].combine_first(met["eqp_body_status_change_time"])

    fallback_issue = met["eqp_body_eqp_status"].where(met["eqp_body_eqp_status"].isin(["LOCAL", "PM", "DOWN"]))
    met["eqpissue"] = met["tip_eqpissue"].combine_first(fallback_issue)

    hold_work = hold.copy()
    hold_work["lot_id"] = hold_work["lot_id"].fillna("").astype(str).str.strip()
    hold_work["step_seq"] = hold_work["step_seq"].fillna("").astype(str).str.strip()
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


def build_wip_concat(wip: pd.DataFrame) -> pd.DataFrame:
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
    if "tip_eqpline" in work.columns:
        base["eqpline"] = work.groupby(group_keys, dropna=False)["tip_eqpline"].agg(unique_concat_series).values

    base["투입경과일_일"] = base.apply(lambda r: _elapsed_days_float(r.get("sysdate"), r.get("start_date")), axis=1)
    base["step도착경과_일"] = base.apply(lambda r: calculate_day_diff(r.get("sysdate"), r.get("step_arrive_date")), axis=1)
    base["마지막event경과_일"] = base.apply(lambda r: calculate_day_diff(r.get("sysdate"), r.get("last_event_date")), axis=1)
    print("[concat 경과일] step도착경과_일 / 마지막event경과_일 DAY 단위 계산 완료")

    work["_prevent_item"] = work.apply(make_prevent_item, axis=1)
    prevent_items = (
        work.groupby(group_keys, dropna=False)["_prevent_item"]
        .apply(lambda s: ", ".join(sorted(set([_normalize_text(v) for v in s if _normalize_text(v)]))) if any(_normalize_text(v) for v in s) else pd.NA)
    )
    base["prevent"] = prevent_items.values
    base["prevent"] = base["prevent"].apply(lambda x: pd.NA if pd.isna(x) else f"PREVENT: {x}")
    print("[concat 검증] prevent tip_tip_eventtime 기준 경과일 계산 완료")

    issue_candidate_cols = ["eqpissuetime", "tip_eqpissuetime", "tip_tip_eventtime", "eqp_body_status_change_time", "body_status_change_time", "body_status_change_time_eqp"]
    print("[issue_eqp 진단] 시간 후보 컬럼 존재 여부:")
    for c in issue_candidate_cols:
        print(f"- {c}: {c in work.columns}")

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
    sys_ok = int(issue_target["_sysdate_dt"].notna().sum()) if total_issue_target else 0
    print(f"[issue_eqp 진단] sysdate 파싱 성공: {sys_ok} / {total_issue_target}")

    eqpissue_col = "eqpissuetime" if "eqpissuetime" in work.columns else ("tip_eqpissuetime" if "tip_eqpissuetime" in work.columns else None)
    body_col = "eqp_body_status_change_time" if "eqp_body_status_change_time" in work.columns else ("body_status_change_time" if "body_status_change_time" in work.columns else ("body_status_change_time_eqp" if "body_status_change_time_eqp" in work.columns else None))
    print(f"[issue_eqp 진단] eqpissuetime 컬럼 존재: {eqpissue_col is not None}")
    print(f"[issue_eqp 진단] eqp_body_status_change_time 컬럼 존재: {body_col is not None}")

    issue_target["_issue_a"] = safe_to_datetime(issue_target[eqpissue_col]) if (total_issue_target and eqpissue_col) else pd.NaT
    issue_target["_issue_b"] = safe_to_datetime(issue_target[body_col]) if (total_issue_target and body_col) else pd.NaT
    a_ok = int(issue_target["_issue_a"].notna().sum()) if total_issue_target else 0
    b_ok = int(issue_target["_issue_b"].notna().sum()) if total_issue_target else 0
    print(f"[issue_eqp 진단] eqpissuetime 파싱 성공: {a_ok} / {total_issue_target}")
    print(f"[issue_eqp 진단] eqp_body_status_change_time 파싱 성공: {b_ok} / {total_issue_target}")

    if total_issue_target:
        issue_target["_issue_ref"] = issue_target[["_issue_a", "_issue_b"]].min(axis=1)
        both_fail = int((issue_target["_issue_a"].isna() & issue_target["_issue_b"].isna()).sum())
        ref_ok = int(issue_target["_issue_ref"].notna().sum())
        issue_fail = int((issue_target["_sysdate_dt"].isna() | issue_target["_issue_ref"].isna()).sum())
    else:
        both_fail = ref_ok = issue_fail = 0
    print(f"[issue_eqp 진단] 두 날짜 모두 파싱 실패: {both_fail} / {total_issue_target}")
    print(f"[issue_eqp 진단] 기준일 계산 성공: {ref_ok} / {total_issue_target}")
    print(f"[issue_eqp 진단] 경과일계산불가 item 수: {issue_fail}")

    if eqpissue_col and eqpissue_col != "eqpissuetime":
        print(f"[issue_eqp 진단] fallback 적용: eqpissuetime 대신 {eqpissue_col} 사용")
    if body_col and body_col != "eqp_body_status_change_time":
        print(f"[issue_eqp 진단] fallback 적용: eqp_body_status_change_time 대신 {body_col} 사용")

    if eqpissue_col:
        work["eqpissuetime"] = work[eqpissue_col]
    if body_col:
        work["eqp_body_status_change_time"] = work[body_col]

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
    print("[concat 검증] issue_eqp 기준일 min(eqpissuetime, eqp_body_status_change_time) 계산 완료")

    base = apply_wait_blocked_status(base, work, group_keys)

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
        "ftp", "ftp_user", "ftp_reason", "ftp_date",
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
        "mcpath": Path(MCPATH_PATH),
        "tip": Path(TIP_PATH),
    }

    mcpath, mcpath_meta = read_input_csv("mcpath", paths["mcpath"])
    eqp, eqp_meta = read_input_csv("eqp", paths["eqp"])
    tip, tip_meta = read_input_csv("tip", paths["tip"])
    hold, hold_meta = read_input_csv("hold", paths["hold"])

    wip = build_wip(mcpath, eqp, tip, hold)

    output_path = next_available_path(script_dir / "output_wip.xlsx")
    dup_cnt = int(wip.duplicated().sum())
    if dup_cnt > 0:
        print(f"[경고] 최종 wip 완전중복 rows가 {dup_cnt}건입니다. duplicate_debug 파일을 저장합니다.")
        debug_path = next_available_path(script_dir / "duplicate_debug.xlsx")
        wip.loc[wip.duplicated(keep=False)].to_excel(debug_path, index=False)
        print(f"[중복 디버그] 저장 완료: {debug_path}")
        before = len(wip)
        wip = wip.drop_duplicates()
        print(f"[중복 보정] 원인 축약 후에도 완전중복 {before - len(wip)}건이 남아 최종 저장 전 drop_duplicates로 제거했습니다.")

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        wip.to_excel(writer, index=False)
    print(f"[wip 저장 완료] 경로: {output_path}")

    wip_concat = build_wip_concat(wip)
    output_concat_path = next_available_path(script_dir / "output_wip_concat.xlsx")
    with pd.ExcelWriter(output_concat_path, engine="openpyxl") as writer:
        wip_concat.to_excel(writer, index=False)
    print(f"[concat 저장 완료] 경로: {output_concat_path}")

    print("[입력 파일 요약]")
    for name, meta in [("eqp", eqp_meta), ("hold", hold_meta), ("mcpath", mcpath_meta), ("tip", tip_meta)]:
        print(f"- {name} path: {meta['path']}")
        print(f"  size={meta['size']} bytes, rows={meta['rows']}, cols={meta['cols']}, encoding={meta['encoding']}, sep={meta['separator']}")

    print(f"[wip] row={len(wip)}, col={len(wip.columns)}")
    print(f"[결과 요약] output_wip rows: {len(wip)}")
    print(f"[결과 요약] output_wip_concat rows: {len(wip_concat)}")


if __name__ == "__main__":
    try:
        main()
    except WipBuildError as exc:
        print(f"오류: {exc}")
        raise SystemExit(1)
