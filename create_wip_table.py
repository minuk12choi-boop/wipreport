from __future__ import annotations

from pathlib import Path

import pandas as pd


EQP_PATH = r"C:\Users\minuk12.choi\Documents\zhbm_eqpmaster.xlsx"
HOLD_PATH = r"C:\Users\minuk12.choi\Documents\zhbm_hold.xlsx"
MCPATH_PATH = r"C:\Users\minuk12.choi\Documents\zhbm_mclotsteppath.xlsx"
TIP_PATH = r"C:\Users\minuk12.choi\Documents\zhbm_tip.xlsx"

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


class WipBuildError(Exception):
    pass


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    return df


def _assert_required_columns(df: pd.DataFrame, name: str) -> None:
    missing = [c for c in REQUIRED_COLUMNS[name] if c not in df.columns]
    if missing:
        raise WipBuildError(f"{name} 파일에 필요한 컬럼이 없습니다: {missing}")


def _load_excel(name: str, path: Path) -> pd.DataFrame:
    if not path.exists():
        raise WipBuildError(f"원천 파일이 존재하지 않습니다: {path}")
    try:
        df = pd.read_excel(path)
    except Exception as exc:
        raise WipBuildError(f"{name} 파일을 읽는 중 오류가 발생했습니다: {path} / {exc}") from exc
    df = _normalize_columns(df)
    _assert_required_columns(df, name)
    return df


def _unique_join_text(series: pd.Series) -> str | None:
    vals = [str(v).strip() for v in series.dropna() if str(v).strip()]
    uniq = list(dict.fromkeys(vals))
    return " | ".join(uniq) if uniq else None


def build_wip(mcpath: pd.DataFrame, eqp: pd.DataFrame, tip: pd.DataFrame, hold: pd.DataFrame) -> pd.DataFrame:
    me = mcpath.merge(
        eqp[["eqp_id", "batch_kind", "eqpline", "body_eqp_status", "body_status_change_time"]],
        on="eqp_id",
        how="left",
        suffixes=("", "_eqp"),
    )

    tip_cols = [
        "eqpcham", "chamberid", "batch_kind", "prevent", "type_body", "type_cham",
        "tip_eventtime", "eqpissue", "body_eqp_status", "cham_eqp_status", "eqpissuetime", "eqpline",
    ]

    tip_specific = tip[
        (tip["process"] != "-") & (tip["step"] != "-") & (tip["ppid"] != "-")
    ]
    met = me.merge(
        tip_specific,
        left_on=["proc_id", "step_seq", "eqp_id", "recipe_id"],
        right_on=["process", "step", "eqpid", "ppid"],
        how="left",
        suffixes=("", "_tip"),
    )

    tip_wild = tip[(tip["prevent"] == "PREVENT") & ((tip["process"] == "-") | (tip["step"] == "-") | (tip["ppid"] == "-"))]

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

    met["body_eqp_status"] = met["body_eqp_status"].combine_first(met["body_eqp_status_eqp"])
    met["batch_kind"] = met["batch_kind"].combine_first(met["batch_kind_eqp"])
    met["eqpline"] = met["eqpline"].combine_first(met["eqpline_eqp"])
    met["eqpissuetime"] = met["eqpissuetime"].combine_first(met["body_status_change_time"])

    fallback_issue = met["body_eqp_status_eqp"].where(met["body_eqp_status_eqp"].isin(["LOCAL", "PM", "DOWN"]))
    met["eqpissue"] = met["eqpissue"].combine_first(fallback_issue)

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

    mcpath = _load_excel("mcpath", paths["mcpath"])
    eqp = _load_excel("eqp", paths["eqp"])
    tip = _load_excel("tip", paths["tip"])
    hold = _load_excel("hold", paths["hold"])

    wip = build_wip(mcpath, eqp, tip, hold)

    output_path = script_dir / "output_wip.xlsx"
    wip.to_excel(output_path, index=False)

    print("[입력 파일 경로]")
    print(f"- eqp: {paths['eqp']}")
    print(f"- hold: {paths['hold']}")
    print(f"- mcpath: {paths['mcpath']}")
    print(f"- tip: {paths['tip']}")
    print("[입력 row 수]")
    print(f"- mcpath: {len(mcpath)}")
    print(f"- eqp: {len(eqp)}")
    print(f"- tip: {len(tip)}")
    print(f"- hold: {len(hold)}")
    print(f"[wip] row={len(wip)}, col={len(wip.columns)}")
    print(f"저장 완료: {output_path}")


if __name__ == "__main__":
    try:
        main()
    except WipBuildError as exc:
        print(f"오류: {exc}")
        raise SystemExit(1)
