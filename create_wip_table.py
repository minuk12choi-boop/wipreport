from __future__ import annotations

from pathlib import Path

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


def _unique_join_text(series: pd.Series) -> str | None:
    vals = [str(v).strip() for v in series.dropna() if str(v).strip()]
    uniq = list(dict.fromkeys(vals))
    return " | ".join(uniq) if uniq else None


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


def log_duplicate_keys(df: pd.DataFrame, keys: list[str], name: str, limit: int = 10) -> None:
    missing = [c for c in keys if c not in df.columns]
    if missing:
        print(f"[중복키 점검] {name}: 키 컬럼 누락 {missing}")
        return
    dup_mask = df.duplicated(subset=keys, keep=False)
    dup_rows = int(dup_mask.sum())
    dup_groups = int(df.loc[dup_mask, keys].drop_duplicates().shape[0]) if dup_rows else 0
    print(f"[중복키 점검] {name}: keys={keys}, duplicated_rows={dup_rows}, duplicated_groups={dup_groups}")
    if dup_rows:
        print(df.loc[dup_mask, keys].value_counts().head(limit))


def build_wip(mcpath: pd.DataFrame, eqp: pd.DataFrame, tip: pd.DataFrame, hold: pd.DataFrame) -> pd.DataFrame:
    print(f"[행수 점검] mcpath 원본: {len(mcpath)}")
    print(f"[행수 점검] eqp 원본: {len(eqp)}")
    print(f"[행수 점검] tip 원본: {len(tip)}")
    print(f"[행수 점검] hold 원본: {len(hold)}")
    log_duplicate_keys(eqp, ["eqp_id"], "eqp 조인 키")
    log_duplicate_keys(tip, ["process", "step", "eqpid", "ppid"], "exact tip 조인 키")
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
    if tip_specific["tip_eventtime_dt"].notna().any() or tip_specific["eqpissuetime_dt"].notna().any():
        tip_specific = tip_specific.sort_values(["tip_eventtime_dt", "eqpissuetime_dt"]).drop_duplicates(
            ["process", "step", "eqpid", "ppid"], keep="last"
        )
    else:
        tip_specific = tip_specific.drop_duplicates(["process", "step", "eqpid", "ppid"], keep="last")
    tip_specific = tip_specific.drop(columns=["tip_eventtime_dt", "eqpissuetime_dt"])
    print(f"[축약 점검] exact tip 축약 후 rows: {len(tip_specific)}")
    before_rows = len(me)
    met = me.merge(
        tip_specific,
        left_on=["proc_id", "step_seq", "eqp_id", "recipe_id"],
        right_on=["process", "step", "eqpid", "ppid"],
        how="left",
    )
    after_rows = len(met)
    print(f"[행수 점검] exact tip 조인 후 rows: {after_rows}")
    print(f"[중복 점검] exact tip 조인 후 완전중복 rows: {met.duplicated().sum()}")
    if after_rows != before_rows:
        raise WipBuildError(f"exact tip 조인 후 행 수가 증가했습니다. before={before_rows}, after={after_rows}. tip 조인키 중복 축약 로직을 확인하세요.")

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
    before_rows = len(me)
    after_rows = len(met)
    print(f"[행수 점검] wildcard tip 반영 후 rows: {after_rows}")
    print(f"[중복 점검] wildcard tip 반영 후 완전중복 rows: {met.drop(columns=['_row_id']).duplicated().sum()}")
    if after_rows != before_rows:
        raise WipBuildError(f"wildcard overlay 후 행 수가 증가했습니다. before={before_rows}, after={after_rows}. wildcard 매칭 축약 로직을 확인하세요.")

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
    print(f"[hold merge 점검] met lot_id+step_seq duplicated rows: {int(met.duplicated(['lot_id', 'step_seq'], keep=False).sum())}")
    print(f"[hold merge 점검] hold_summary rows: {len(hold_summary)}")
    print(f"[hold merge 점검] hold_summary columns: {hold_summary.columns.tolist()}")
    print(f"[hold merge 점검] hold_summary duplicate key rows: {int(hold_summary.duplicated(['lot_id', 'step_seq'], keep=False).sum())}")
    print(f"[hold merge 점검] key overlap unique count: {overlap}")

    met_before = len(met)
    meth = met.merge(hold_summary, on=["lot_id", "step_seq"], how="left", validate="m:1")
    after_rows = len(meth)
    print(f"[행수 점검] hold merge 후 rows: {after_rows}")
    print(f"[중복 점검] hold merge 후 완전중복 rows: {meth.duplicated().sum()}")
    if after_rows != met_before:
        raise WipBuildError(f"hold merge 후 행 수가 증가했습니다. before={met_before}, after={after_rows}. hold 집계/조인 로직을 확인하세요.")
    meth = meth.drop(columns=["_row_id"], errors="ignore")
    print(f"[행수 점검] 최종 wip rows: {len(meth)}")
    print(f"[중복 점검] 최종 wip 완전중복 rows: {meth.duplicated().sum()}")

    return meth


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

    print("[입력 파일 요약]")
    for name, meta in [("eqp", eqp_meta), ("hold", hold_meta), ("mcpath", mcpath_meta), ("tip", tip_meta)]:
        print(f"- {name} path: {meta['path']}")
        print(f"  size={meta['size']} bytes, rows={meta['rows']}, cols={meta['cols']}, encoding={meta['encoding']}, sep={meta['separator']}")

    print(f"[wip] row={len(wip)}, col={len(wip.columns)}")
    print(f"저장 완료: {output_path}")


if __name__ == "__main__":
    try:
        main()
    except WipBuildError as exc:
        print(f"오류: {exc}")
        raise SystemExit(1)
