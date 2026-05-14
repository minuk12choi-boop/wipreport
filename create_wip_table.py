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


def _unique_join_text(series: pd.Series) -> str | None:
    vals = [str(v).strip() for v in series.dropna() if str(v).strip()]
    uniq = list(dict.fromkeys(vals))
    return " | ".join(uniq) if uniq else None


def build_wip(mcpath: pd.DataFrame, eqp: pd.DataFrame, tip: pd.DataFrame, hold: pd.DataFrame) -> pd.DataFrame:
    eqp_renamed = eqp.rename(columns={
        "body_eqp_status": "eqp_body_eqp_status",
        "body_status_change_time": "eqp_body_status_change_time",
        "batch_kind": "eqp_batch_kind",
        "eqpline": "eqp_eqpline",
    })

    me = mcpath.merge(
        eqp_renamed[["eqp_id", "eqp_batch_kind", "eqp_eqpline", "eqp_body_eqp_status", "eqp_body_status_change_time"]],
        on="eqp_id",
        how="left",
    )

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
    ]
    met = me.merge(
        tip_specific,
        left_on=["proc_id", "step_seq", "eqp_id", "recipe_id"],
        right_on=["process", "step", "eqpid", "ppid"],
        how="left",
    )

    tip_wild = tip_renamed[
        (tip_renamed["tip_prevent"] == "PREVENT")
        & ((tip_renamed["process"] == "-") | (tip_renamed["step"] == "-") | (tip_renamed["ppid"] == "-"))
    ]

    for _, r in tip_wild.iterrows():
        mask = met["eqp_id"].eq(r["eqpid"])
        if r["process"] != "-":
            mask &= met["proc_id"].eq(r["process"])
        if r["step"] != "-":
            mask &= met["step_seq"].eq(r["step"])
        if r["ppid"] != "-":
            mask &= met["recipe_id"].eq(r["ppid"])
        for c in tip_cols:
            met.loc[mask, c] = r[c]

    met["body_eqp_status"] = met["tip_body_eqp_status"].combine_first(met["eqp_body_eqp_status"])
    met["batch_kind"] = met["tip_batch_kind"].combine_first(met["eqp_batch_kind"])
    met["eqpline"] = met["tip_eqpline"].combine_first(met["eqp_eqpline"])
    met["eqpissuetime"] = met["tip_eqpissuetime"].combine_first(met["eqp_body_status_change_time"])

    fallback_issue = met["eqp_body_eqp_status"].where(met["eqp_body_eqp_status"].isin(["LOCAL", "PM", "DOWN"]))
    met["eqpissue"] = met["tip_eqpissue"].combine_first(fallback_issue)

    hold_filtered = hold[hold["item_type"].isin(["EXCEPTION", "HOLD LOT", "FTkinPvLot", "FUTUREHOLD"])].copy()
    hold_filtered["hold_type"] = hold_filtered["item_type"].replace({
        "EXCEPTION": "예약제외",
        "HOLD LOT": "HOLD",
        "FUTUREHOLD": "HOLD",
        "FTkinPvLot": "FTP",
    })

    hold_agg = hold_filtered.groupby(["lot_id", "step_seq", "hold_type"], as_index=False).agg(
        hold_date=("hold_date", "min"),
        hold_user=("hold_user", _unique_join_text),
        hold_reason=("hold_reason", _unique_join_text),
    )

    hold_pivot = hold_agg.pivot_table(
        index=["lot_id", "step_seq"],
        columns="hold_type",
        values=["hold_date", "hold_user", "hold_reason"],
        aggfunc="first",
    )
    hold_pivot.columns = [f"{k}_{t}" for k, t in hold_pivot.columns]
    hold_pivot = hold_pivot.reset_index()

    for t in ["예약제외", "HOLD", "FTP"]:
        if f"hold_date_{t}" in hold_pivot.columns:
            hold_pivot[t] = "O"

    date_cols = [c for c in hold_pivot.columns if c.startswith("hold_date_")]
    hold_pivot["hold_date"] = hold_pivot[date_cols].min(axis=1) if date_cols else pd.NaT

    hold_pivot = hold_pivot.rename(columns={
        "hold_user_예약제외": "예약제외_user",
        "hold_reason_예약제외": "예약제외_reason",
        "hold_user_HOLD": "HOLD_user",
        "hold_reason_HOLD": "HOLD_reason",
        "hold_user_FTP": "FTP_user",
        "hold_reason_FTP": "FTP_reason",
    })

    non_run = met["status"] != "RUN"
    meth = met.copy()
    joined = meth.loc[non_run].merge(hold_pivot, on=["lot_id", "step_seq"], how="left")
    meth = meth.merge(joined[["lot_id", "order_seq", "step_seq"] + [c for c in joined.columns if c not in meth.columns]],
                      on=["lot_id", "order_seq", "step_seq"], how="left")

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

    output_path = script_dir / "output_wip.xlsx"
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
