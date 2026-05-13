# -*- coding: utf-8 -*-
r"""
create_wip_table.py

README.md 기준으로 mcpath + eqp + tip + hold 데이터를 조인하여 `wip` 테이블을 생성/갱신하는 독립 실행형 스크립트입니다.

전제
- rawdata/*.txt 안의 SQL을 이미 실행해서 CSV 또는 XLSX로 받아둔 상태를 입력으로 사용합니다.
- 이 파일은 Django 모델/마이그레이션을 직접 생성하지 않습니다.
- Django 웹에서 조회할 수 있도록 별도 SQL DB 테이블 `wip`에 결과를 저장합니다.

주요 처리 흐름
1) mcpath(m) + eqp(e) 조인: m.eqp_id = e.eqp_id
2) me + tip(t) 정확 조인: proc_id/process, step_seq/step, eqp_id/eqpid, recipe_id/ppid
3) tip 중 process/step/ppid 값이 '-'인 PREVENT 행은 와일드카드 조인으로 추가 반영
   - '-'인 컬럼은 조인 조건에서 제외
   - t1 와일드카드 매칭값이 정확 조인값보다 우선
4) met + hold(h) 조인
   - met.status <> 'RUN'인 행에만 적용
   - 행 수가 늘어나지 않도록 hold 데이터를 lot_id + step_seq 기준으로 사전 집계
   - EXCEPTION -> 예약제외, HOLD LOT/FUTUREHOLD -> HOLD, FTkinPvLot -> FTP
5) 결과를 CSV 및 SQL 테이블로 저장

Windows VS Code 터미널 예시
    python create_wip_table.py ^
        --mcpath .\data\mclotsteppath.csv ^
        --eqp .\data\eqp.csv ^
        --tip .\data\tip.csv ^
        --hold .\data\hold.csv ^
        --sqlite-db .\db.sqlite3 ^
        --table-name wip ^
        --output-csv .\output\wip.csv

SQLAlchemy 연결 문자열 사용 예시
    python create_wip_table.py --mcpath .\data\mclotsteppath.xlsx --eqp .\data\eqp.xlsx --tip .\data\tip.xlsx --hold .\data\hold.xlsx --db-url "sqlite:///db.sqlite3"
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Iterable

import pandas as pd


DATE_LIKE_COLUMNS = {
    "sysdate",
    "start_date",
    "last_tkout_date",
    "step_arrive_date",
    "last_event_date",
    "body_status_change_time",
    "cham_status_change_time",
    "tip_eventtime",
    "eqpissuetime",
    "hold_date",
    "예약제외_date",
    "hold_date_hold",
    "ftp_date",
}

TIP_ADD_COLUMNS = [
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
]

TIP_MATCH_LEFT = {
    "process": "proc_id",
    "step": "step_seq",
    "ppid": "recipe_id",
}

HOLD_TYPE_MAP = {
    "EXCEPTION": "예약제외",
    "HOLD LOT": "HOLD",
    "FUTUREHOLD": "HOLD",
    "FTkinPvLot": "FTP",
    "FTKINPVLOT": "FTP",
}


def normalize_column_name(col: object) -> str:
    """컬럼명을 비교/조인하기 쉽도록 정규화합니다."""
    return str(col).strip().lower()


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [normalize_column_name(c) for c in out.columns]
    return out


def read_input_table(path: str | Path) -> pd.DataFrame:
    """CSV/XLSX/XLS/Parquet 파일을 읽습니다."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"입력 파일이 없습니다: {p}")

    suffix = p.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        df = pd.read_excel(p)
    elif suffix in {".csv", ".txt"}:
        # utf-8-sig 우선. 실패 시 cp949 재시도.
        try:
            df = pd.read_csv(p, encoding="utf-8-sig")
        except UnicodeDecodeError:
            df = pd.read_csv(p, encoding="cp949")
    elif suffix == ".parquet":
        df = pd.read_parquet(p)
    else:
        raise ValueError(f"지원하지 않는 파일 형식입니다: {p.suffix} ({p})")

    df = normalize_columns(df)
    df = parse_date_columns(df)
    return df


def parse_date_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        if col in DATE_LIKE_COLUMNS or col.endswith("_date") or col.endswith("time"):
            out[col] = pd.to_datetime(out[col], errors="coerce")
    return out


def require_columns(df: pd.DataFrame, required: Iterable[str], table_name: str) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"{table_name} 필수 컬럼 누락: {missing}")


def as_clean_key(series: pd.Series) -> pd.Series:
    """조인 키 비교용 문자열 정규화. NULL은 빈 문자열로 둡니다."""
    return series.fillna("").astype(str).str.strip()


def unique_concat(values: pd.Series) -> str | None:
    """NULL/공백 제외 후 unique 값을 | 로 연결합니다."""
    items: list[str] = []
    seen: set[str] = set()
    for value in values:
        if pd.isna(value):
            continue
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        items.append(text)
    return " | ".join(items) if items else None


def first_non_null(values: pd.Series):
    valid = values.dropna()
    return valid.iloc[0] if not valid.empty else pd.NA


def latest_deduplicate_tip(tip: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """tip 중 동일 키가 여러 건이면 tip_eventtime/eqpissuetime 기준 최신 1건만 남깁니다."""
    if tip.empty:
        return tip.copy()

    sort_cols = [c for c in ["tip_eventtime", "eqpissuetime"] if c in tip.columns]
    out = tip.copy()
    for key in keys:
        if key not in out.columns:
            out[key] = pd.NA
    if sort_cols:
        out = out.sort_values(sort_cols, na_position="first")
    return out.drop_duplicates(subset=keys, keep="last")


def merge_eqp(mcpath: pd.DataFrame, eqp: pd.DataFrame) -> pd.DataFrame:
    require_columns(mcpath, ["eqp_id"], "mcpath")
    require_columns(eqp, ["eqp_id"], "eqp")

    eqp_cols = [
        c
        for c in ["eqp_id", "batch_kind", "eqpline", "body_eqp_status", "body_status_change_time"]
        if c in eqp.columns
    ]
    e = eqp[eqp_cols].copy()
    e["eqp_id"] = as_clean_key(e["eqp_id"])
    e = e.drop_duplicates(subset=["eqp_id"], keep="last")

    m = mcpath.copy()
    m["eqp_id"] = as_clean_key(m["eqp_id"])

    merged = m.merge(e, on="eqp_id", how="left", suffixes=("", "_eqp"))
    return merged


def merge_tip_exact(me: pd.DataFrame, tip: pd.DataFrame) -> pd.DataFrame:
    require_columns(me, ["proc_id", "step_seq", "eqp_id", "recipe_id"], "mcpath/eqp 조인 결과")
    require_columns(tip, ["process", "step", "eqpid", "ppid"], "tip")

    left = me.copy()
    for col in ["proc_id", "step_seq", "eqp_id", "recipe_id"]:
        left[col] = as_clean_key(left[col])

    needed_tip_cols = ["process", "step", "eqpid", "ppid"] + [c for c in TIP_ADD_COLUMNS if c in tip.columns]
    t = tip[needed_tip_cols].copy()
    for col in ["process", "step", "eqpid", "ppid"]:
        t[col] = as_clean_key(t[col])

    t_exact = t[(t["process"] != "-") & (t["step"] != "-") & (t["ppid"] != "-")].copy()
    t_exact = latest_deduplicate_tip(t_exact, ["process", "step", "eqpid", "ppid"])

    merged = left.merge(
        t_exact,
        how="left",
        left_on=["proc_id", "step_seq", "eqp_id", "recipe_id"],
        right_on=["process", "step", "eqpid", "ppid"],
        suffixes=("", "_tip"),
    )

    # 조인용 중복 컬럼은 결과에서 제거합니다.
    return merged.drop(columns=[c for c in ["process", "step", "eqpid", "ppid"] if c in merged.columns])


def collect_wildcard_tip_matches(met: pd.DataFrame, tip: pd.DataFrame) -> pd.DataFrame:
    """
    process/step/ppid 중 '-'가 포함된 PREVENT tip 행을 와일드카드로 매칭합니다.
    반환값은 _row_id별 최종 t1 후보입니다.
    """
    required_tip_cols = ["process", "step", "eqpid", "ppid", "prevent"]
    if any(c not in tip.columns for c in required_tip_cols):
        return pd.DataFrame()

    base = met.copy()
    base["_row_id"] = range(len(base))
    for col in ["proc_id", "step_seq", "eqp_id", "recipe_id"]:
        if col in base.columns:
            base[col] = as_clean_key(base[col])

    t = tip.copy()
    for col in ["process", "step", "eqpid", "ppid", "prevent"]:
        t[col] = as_clean_key(t[col])

    wildcard = t[
        (t["prevent"] == "PREVENT")
        & ((t["process"] == "-") | (t["step"] == "-") | (t["ppid"] == "-"))
    ].copy()
    if wildcard.empty:
        return pd.DataFrame()

    matches: list[pd.DataFrame] = []

    # 7개 패턴: process/step/ppid 중 일부가 '-'인 경우.
    dim_cols = ["process", "step", "ppid"]
    for _, sample in wildcard[dim_cols].drop_duplicates().iterrows():
        pattern = {col: sample[col] for col in dim_cols}
        pattern_mask = pd.Series(True, index=wildcard.index)
        for col, value in pattern.items():
            pattern_mask &= wildcard[col] == value
        part = wildcard[pattern_mask].copy()

        non_wild_dims = [col for col in dim_cols if pattern[col] != "-"]
        left_keys = [TIP_MATCH_LEFT[col] for col in non_wild_dims] + ["eqp_id"]
        right_keys = non_wild_dims + ["eqpid"]

        # 패턴 안에서도 동일 매칭 키가 여러 건이면 최신 1건으로 축약합니다.
        part = latest_deduplicate_tip(part, right_keys)

        merged = base[["_row_id"] + left_keys].merge(
            part,
            how="inner",
            left_on=left_keys,
            right_on=right_keys,
        )
        if merged.empty:
            continue
        merged["_specificity"] = len(non_wild_dims)
        matches.append(merged)

    if not matches:
        return pd.DataFrame()

    all_matches = pd.concat(matches, ignore_index=True)
    sort_cols = ["_specificity"] + [c for c in ["tip_eventtime", "eqpissuetime"] if c in all_matches.columns]
    all_matches = all_matches.sort_values(sort_cols, na_position="first")
    return all_matches.drop_duplicates(subset=["_row_id"], keep="last")


def overlay_tip_values(met: pd.DataFrame, wildcard_match: pd.DataFrame) -> pd.DataFrame:
    """t1 값이 있으면 기존 t 값보다 우선 적용합니다."""
    if wildcard_match.empty:
        return met

    out = met.copy()
    out["_row_id"] = range(len(out))

    use_cols = ["_row_id"] + [c for c in TIP_ADD_COLUMNS if c in wildcard_match.columns]
    t1 = wildcard_match[use_cols].copy()
    t1 = t1.rename(columns={c: f"{c}_t1" for c in use_cols if c != "_row_id"})

    out = out.merge(t1, on="_row_id", how="left")
    for col in TIP_ADD_COLUMNS:
        t1_col = f"{col}_t1"
        if t1_col not in out.columns:
            continue
        if col not in out.columns:
            out[col] = pd.NA
        out[col] = out[t1_col].combine_first(out[col])

    drop_cols = ["_row_id"] + [c for c in out.columns if c.endswith("_t1")]
    return out.drop(columns=drop_cols)


def apply_tip_final_overrides(met: pd.DataFrame) -> pd.DataFrame:
    """
    README의 변경필요컬럼 규칙을 최종 컬럼에 반영합니다.
    - body_eqp_status = nvl(t.body_eqp_status, me.body_eqp_status)
    - batch_kind      = nvl(t.batch_kind, me.batch_kind)
    - eqpline         = nvl(t.eqpline, me.eqpline)
    - eqpissuetime    = nvl(t.eqpissuetime, me.body_status_change_time)
    - eqpissue        = nvl(t.eqpissue, me.body_eqp_status in LOCAL/PM/DOWN then me.body_eqp_status)
    """
    out = met.copy()

    # merge suffix 때문에 원본/팁 컬럼이 나뉜 경우를 보정합니다.
    # pandas merge 결과에서 좌측에 이미 있던 batch_kind/body_eqp_status/eqpline은 그대로 남고,
    # tip 쪽 동일명 컬럼은 *_tip으로 생길 수 있습니다.
    for col in ["batch_kind", "body_eqp_status", "eqpline"]:
        tip_col = f"{col}_tip"
        if tip_col in out.columns:
            out[col] = out[tip_col].combine_first(out.get(col, pd.Series(pd.NA, index=out.index)))
            out = out.drop(columns=[tip_col])

    if "eqpissuetime" not in out.columns:
        out["eqpissuetime"] = pd.NA
    if "body_status_change_time" in out.columns:
        out["eqpissuetime"] = out["eqpissuetime"].combine_first(out["body_status_change_time"])

    if "eqpissue" not in out.columns:
        out["eqpissue"] = pd.NA
    if "body_eqp_status" in out.columns:
        fallback_issue = out["body_eqp_status"].where(out["body_eqp_status"].isin(["LOCAL", "PM", "DOWN"]))
        out["eqpissue"] = out["eqpissue"].combine_first(fallback_issue)

    # exact merge에서 남은 tip 조인 키/중복 컬럼 정리
    redundant = [c for c in ["process", "step", "eqpid", "ppid"] if c in out.columns]
    if redundant:
        out = out.drop(columns=redundant)

    return out


def build_hold_summary(hold: pd.DataFrame) -> pd.DataFrame:
    require_columns(hold, ["item_type", "lot_id", "step_seq"], "hold")

    h = hold.copy()
    h["lot_id"] = as_clean_key(h["lot_id"])
    h["step_seq"] = as_clean_key(h["step_seq"])
    h["_hold_category"] = h["item_type"].astype(str).str.strip().map(HOLD_TYPE_MAP)
    h = h[h["_hold_category"].notna()].copy()

    if h.empty:
        return pd.DataFrame(columns=["lot_id", "step_seq", "예약제외", "HOLD", "FTP", "hold_date"])

    if "hold_date" in h.columns:
        h["hold_date"] = pd.to_datetime(h["hold_date"], errors="coerce")

    key_cols = ["lot_id", "step_seq"]
    result = h[key_cols].drop_duplicates().copy()

    # 전체 hold_date는 세 유형 중 가장 이른 날짜 1개만 사용합니다.
    if "hold_date" in h.columns:
        min_date = h.groupby(key_cols, dropna=False)["hold_date"].min().reset_index(name="hold_date")
        result = result.merge(min_date, on=key_cols, how="left")

    for category in ["예약제외", "HOLD", "FTP"]:
        part = h[h["_hold_category"] == category].copy()
        if part.empty:
            result[category] = pd.NA
            result[f"{category}_user"] = pd.NA
            result[f"{category}_reason"] = pd.NA
            result[f"{category}_date"] = pd.NaT
            continue

        agg_dict = {}
        if "hold_user" in part.columns:
            agg_dict["hold_user"] = unique_concat
        if "hold_reason" in part.columns:
            agg_dict["hold_reason"] = unique_concat
        if "hold_date" in part.columns:
            agg_dict["hold_date"] = "min"

        aggregated = part.groupby(key_cols, dropna=False).agg(agg_dict).reset_index()
        rename = {}
        if "hold_user" in aggregated.columns:
            rename["hold_user"] = f"{category}_user"
        if "hold_reason" in aggregated.columns:
            rename["hold_reason"] = f"{category}_reason"
        if "hold_date" in aggregated.columns:
            rename["hold_date"] = f"{category}_date"
        aggregated = aggregated.rename(columns=rename)
        aggregated[category] = "O"

        result = result.merge(aggregated, on=key_cols, how="left")

    return result


def merge_hold(met: pd.DataFrame, hold: pd.DataFrame) -> pd.DataFrame:
    require_columns(met, ["lot_id", "step_seq", "status"], "tip 조인 결과")

    out = met.copy()
    out["lot_id"] = as_clean_key(out["lot_id"])
    out["step_seq"] = as_clean_key(out["step_seq"])

    hold_summary = build_hold_summary(hold)
    if hold_summary.empty:
        return out

    out["_row_id"] = range(len(out))
    join_target = out[out["status"].fillna("").astype(str).str.upper() != "RUN"].copy()
    not_target = out[out["status"].fillna("").astype(str).str.upper() == "RUN"].copy()

    joined = join_target.merge(hold_summary, on=["lot_id", "step_seq"], how="left")
    result = pd.concat([joined, not_target], ignore_index=True).sort_values("_row_id")
    return result.drop(columns=["_row_id"])


def build_wip(mcpath: pd.DataFrame, eqp: pd.DataFrame, tip: pd.DataFrame, hold: pd.DataFrame) -> pd.DataFrame:
    me = merge_eqp(mcpath, eqp)
    met = merge_tip_exact(me, tip)
    wildcard_match = collect_wildcard_tip_matches(met, tip)
    met = overlay_tip_values(met, wildcard_match)
    met = apply_tip_final_overrides(met)
    meth = merge_hold(met, hold)

    # 생성 시각 컬럼 추가. 원본 SYSDATE가 있으면 유지하고, 적재 시각은 별도로 둡니다.
    meth["loaded_at"] = pd.Timestamp.now().floor("s")
    return meth


def write_output_csv(df: pd.DataFrame, path: str | Path | None) -> None:
    if not path:
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(p, index=False, encoding="utf-8-sig")


def write_sql_table(df: pd.DataFrame, table_name: str, sqlite_db: str | None = None, db_url: str | None = None, if_exists: str = "replace") -> None:
    if db_url:
        try:
            from sqlalchemy import create_engine
        except ImportError as exc:
            raise RuntimeError("--db-url 사용 시 SQLAlchemy가 필요합니다. pip install sqlalchemy 후 다시 실행하세요.") from exc
        engine = create_engine(db_url)
        with engine.begin() as conn:
            df.to_sql(table_name, conn, if_exists=if_exists, index=False)
        return

    if sqlite_db:
        db_path = Path(sqlite_db)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db_path) as conn:
            df.to_sql(table_name, conn, if_exists=if_exists, index=False)
        return

    raise ValueError("SQL 저장 대상이 없습니다. --sqlite-db 또는 --db-url 중 하나를 지정하세요.")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="README 기준 wip 테이블 생성 스크립트")
    parser.add_argument("--mcpath", required=True, help="mclotsteppath 결과 CSV/XLSX 경로")
    parser.add_argument("--eqp", required=True, help="eqp 결과 CSV/XLSX 경로")
    parser.add_argument("--tip", required=True, help="tip 결과 CSV/XLSX 경로")
    parser.add_argument("--hold", required=True, help="hold 결과 CSV/XLSX 경로")
    parser.add_argument("--sqlite-db", default="wipreport.sqlite3", help="SQLite DB 파일 경로. 기본값: wipreport.sqlite3")
    parser.add_argument("--db-url", default=None, help="SQLAlchemy DB URL. 지정 시 --sqlite-db보다 우선")
    parser.add_argument("--table-name", default="wip", help="생성/갱신할 테이블명. 기본값: wip")
    parser.add_argument("--if-exists", default="replace", choices=["fail", "replace", "append"], help="to_sql if_exists 옵션. 기본값: replace")
    parser.add_argument("--output-csv", default=None, help="검증용 결과 CSV 저장 경로")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    mcpath = read_input_table(args.mcpath)
    eqp = read_input_table(args.eqp)
    tip = read_input_table(args.tip)
    hold = read_input_table(args.hold)

    wip = build_wip(mcpath=mcpath, eqp=eqp, tip=tip, hold=hold)

    write_output_csv(wip, args.output_csv)
    write_sql_table(
        wip,
        table_name=args.table_name,
        sqlite_db=args.sqlite_db,
        db_url=args.db_url,
        if_exists=args.if_exists,
    )

    print(f"wip 생성 완료: rows={len(wip):,}, cols={len(wip.columns):,}, table={args.table_name}")
    if args.output_csv:
        print(f"검증 CSV 저장: {Path(args.output_csv).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
