"""성과 데이터 표준화: 링크 수집 지표 + (YouTube 슬롯 한정) Google Ads CSV."""
from __future__ import annotations

import re

import pandas as pd

STD_COLS = ["date", "platform", "campaign", "impressions", "views", "reach", "clicks",
            "cost", "conversions", "conv_value", "currency"]
NUMERIC = ["impressions", "views", "reach", "clicks", "cost", "conversions", "conv_value"]

# Google Ads / YouTube 보고서 열 이름(영문·국문) → 표준 열
ALIASES = {
    "date": ["date", "day", "일", "날짜", "일자"],
    "campaign": ["campaign", "캠페인", "캠페인명", "campaign name"],
    "impressions": ["impressions", "impr.", "impr", "노출수", "노출"],
    "views": ["views", "trueview views", "조회수", "동영상 조회수", "video views"],
    "reach": ["reach", "unique users", "도달", "도달수", "순 사용자"],
    "clicks": ["clicks", "클릭수", "클릭"],
    "cost": ["cost", "비용", "지출", "spend"],
    "conversions": ["conversions", "전환", "전환수", "conv."],
    "conv_value": ["conv. value", "conversion value", "전환 가치", "전환가치", "all conv. value"],
    "currency": ["currency", "currency code", "통화", "통화 코드"],
}

METRIC_DEFINITIONS = pd.DataFrame([
    ("조회수 (YouTube 공개)", "영상 페이지에 표시되는 누적 공개 조회수. 광고 조회와 오가닉 조회가 합산됨", "YouTube 공개 페이지"),
    ("조회수 (Google Ads)", "인스트림 광고 30초(또는 전체) 시청 또는 광고 상호작용 시 1회", "Google Ads CSV"),
    ("노출수", "광고가 화면에 표시된 횟수", "Google Ads CSV"),
    ("도달수", "광고를 1회 이상 본 순 사용자 수 (추정치)", "Google Ads CSV"),
    ("클릭수", "광고 클릭(랜딩 이동) 횟수", "Google Ads CSV"),
    ("비용", "집행 비용, 통화 환산 기준에 따라 KRW로 통일", "Google Ads CSV"),
    ("전환수", "설정된 전환 액션 발생 수 (어트리뷰션 모델·기여 기간 기준)", "Google Ads CSV"),
    ("좋아요", "게시물 공개 좋아요 수", "YouTube/Instagram 공개 정보"),
    ("댓글 수", "게시물 공개 댓글 수 (YouTube는 수집된 표본 수)", "YouTube/Instagram 공개 정보"),
    ("참여율", "(좋아요+댓글)/조회수. 조회수 미제공 플랫폼은 산출 불가", "계산 지표"),
    ("전환율 (CVR)", "전환수/클릭수", "계산 지표"),
    ("전환당 비용 (CPA)", "비용/전환수", "계산 지표"),
], columns=["지표", "정의", "출처"])


def _match(col: str) -> str | None:
    c = col.strip().lower()
    for std, names in ALIASES.items():
        if c in names:
            return std
    return None


def _to_num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(r"[^\d.\-]", "", regex=True).replace("", None), errors="coerce")


def normalize_ads_csv(raw: pd.DataFrame, platform: str, campaign_name: str, fx: dict,
                      default_currency: str = "KRW") -> tuple[pd.DataFrame, list[str]]:
    """Google Ads 보고서 CSV → 표준 스키마. (df, 경고 리스트) 반환. 실패 시 ValueError."""
    warnings = []
    rename = {c: _match(c) for c in raw.columns if _match(c)}
    df = raw.rename(columns=rename)
    df = df.loc[:, ~df.columns.duplicated()]
    if "date" not in df.columns:
        raise ValueError("날짜 열을 찾을 수 없습니다. 'Day', 'Date', '일', '날짜' 중 하나의 열 이름을 사용하세요.")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    bad = int(df["date"].isna().sum())
    if bad:
        warnings.append(f"날짜 형식 오류 {bad}행 제외 (합계 행 포함 가능)")
        df = df.dropna(subset=["date"])
    if "campaign" not in df.columns:
        df["campaign"] = campaign_name
    if "currency" not in df.columns:
        df["currency"] = default_currency
        warnings.append(f"통화 열 없음 → {default_currency}로 간주")
    for c in NUMERIC:
        if c in df.columns:
            df[c] = _to_num(df[c])
        else:
            df[c] = pd.NA
    missing = [c for c in NUMERIC if df[c].isna().all()]
    if missing:
        warnings.append("데이터 누락 지표: " + ", ".join(missing))
    rate = df["currency"].map(lambda x: fx.get(str(x).upper().strip()))
    unknown = df.loc[rate.isna(), "currency"].unique().tolist()
    if unknown:
        warnings.append(f"환율 미등록 통화 {unknown} → 비용 환산 불가 행은 비용 결측 처리")
    for c in ["cost", "conv_value"]:
        df[c] = df[c] * rate
    df["currency"] = "KRW"
    df["platform"] = platform
    df["date"] = df["date"].dt.normalize()
    return df[STD_COLS], warnings


def merge_dedupe(existing: pd.DataFrame | None, new: pd.DataFrame) -> pd.DataFrame:
    """(date, platform, campaign) 기준 중복 제거 — 같은 기간 재업로드 시 최신 값으로 대체."""
    base = new if existing is None or existing.empty else pd.concat([existing, new])
    return base.drop_duplicates(subset=["date", "platform", "campaign"], keep="last").sort_values("date").reset_index(drop=True)


def ads_summary(df: pd.DataFrame) -> dict:
    agg = {c: float(df[c].sum(min_count=1)) if df[c].notna().any() else None for c in NUMERIC}
    agg["cvr"] = agg["conversions"] / agg["clicks"] if agg.get("conversions") and agg.get("clicks") else None
    agg["cpa"] = agg["cost"] / agg["conversions"] if agg.get("cost") and agg.get("conversions") else None
    agg["period"] = f"{df['date'].min():%Y-%m-%d} ~ {df['date'].max():%Y-%m-%d}"
    return agg


def link_metrics_row(slot_label: str, meta: dict, n_comments_collected: int | None = None) -> dict:
    views, likes = meta.get("views"), meta.get("likes")
    comments = meta.get("comments") if meta.get("comments") is not None else n_comments_collected
    eng = (likes or 0) + (comments or 0)
    return {
        "슬롯": slot_label,
        "매체": meta.get("platform"),
        "캠페인명": meta.get("campaign_name") or meta.get("title"),
        "계정": meta.get("account"),
        "시작일": meta.get("start_date") or meta.get("published"),
        "조회수": views,
        "좋아요": likes,
        "댓글 수": comments,
        "참여율": (eng / views) if views else None,
        "데이터 출처": meta.get("source"),
        "수집 시각": meta.get("fetched_at"),
    }


def safe_name(s: str) -> str:
    return re.sub(r"[^\w가-힣]+", "_", s).strip("_")
