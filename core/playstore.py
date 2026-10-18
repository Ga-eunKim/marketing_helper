"""Google Play 스토어 리뷰 → 일별 리뷰 수(다운로드 프록시)·평균 별점 (google-play-scraper, API 키 불필요).

최신순으로 페이지를 넘기며 since 이전 리뷰가 나올 때까지 모은다. 결과는 일별 집계만 디스크 캐시에 저장
(리뷰 본문·작성자는 저장하지 않음).
"""
from __future__ import annotations

import time
from datetime import date, datetime

import pandas as pd
from google_play_scraper import Sort, reviews

from . import cache
from .i18n import t


class StoreError(Exception):
    pass


def _collect(app_id: str, since: date, lang: str, country: str, max_pages: int = 1500) -> pd.DataFrame:
    rows, token = [], None
    for _ in range(max_pages):
        for attempt in range(3):
            try:
                batch, token = reviews(app_id, lang=lang, country=country, sort=Sort.NEWEST, count=200,
                                       continuation_token=token)
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(3 * (attempt + 1))
        rows += [(r["at"], r["score"]) for r in batch]
        if not batch or not token or batch[-1]["at"].date() < since:
            break
        time.sleep(0.3)
    if not rows:
        raise StoreError(t("스토어 리뷰를 가져오지 못했습니다.", "Couldn't fetch store reviews."))
    if rows[-1][0].date() > since:  # 페이지 상한에 걸려 since까지 못 내려간 경우
        raise StoreError(t(f"{lang} 리뷰가 {rows[-1][0].date()}까지만 수집되어 시작일({since})에 못 미칩니다.",
                           f"{lang} reviews only reach back to {rows[-1][0].date()}, short of {since}."))
    df = pd.DataFrame(rows, columns=["at", "score"])
    df["date"] = pd.to_datetime(df["at"]).dt.normalize()
    df = df[df["date"] >= pd.Timestamp(since)]
    daily = df.groupby("date").agg(reviews=("score", "size"), rating=("score", "mean"))
    daily = daily.reindex(pd.date_range(daily.index.min(), daily.index.max(), freq="D"), fill_value=0)
    daily.index.name = "date"
    daily["rating"] = daily["rating"].astype(float).where(daily["reviews"] > 0)  # 리뷰 없는 날은 평점 없음
    daily["reviews_ma7"] = daily["reviews"].rolling(7, min_periods=1).mean()
    daily.attrs["fetched_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return daily


def daily_reviews(app_id: str, since: date, lang: str = "ko", country: str = "kr", refresh: bool = False) -> pd.DataFrame:
    """일별 신규 리뷰 수(reviews), 평균 별점(rating), 7일 이동평균(reviews_ma7).

    저장된 리뷰는 만료되지 않는다 — 수집에 언어별로 수 분이 걸려 화면에서 다시 받으면 페이지가 멈추기 때문.
    새로 받기는 refresh=True(scripts/warm_cache.py)로만 한다.
    """
    return cache.cached("store", (app_id, since.isoformat(), lang, country),
                        lambda: _collect(app_id, since, lang, country), None, refresh)


# 글로벌 집계용 언어·국가 (리뷰는 언어 기준으로 나뉨 — 국가 코드는 스토어 지역 표기용)
GLOBAL_LOCALES = [("en", "us"), ("ko", "kr"), ("es", "mx"), ("pt", "br"), ("th", "th"), ("id", "id"),
                  ("fr", "fr"), ("de", "de"), ("zh-TW", "tw"), ("ja", "jp")]


def daily_reviews_global(app_id: str, since: date, locales=None, refresh: bool = False) -> tuple[pd.DataFrame, list[str]]:
    """여러 언어 리뷰를 합산한 글로벌 일별 리뷰 수. (df, 실패한 언어 목록) 반환.

    df 열: reviews(합계), reviews_ma7, rating(리뷰 수 가중 평균), 그리고 언어별 리뷰 수 rv_<lang>.
    """
    parts, failed = {}, []
    for lang, country in locales or GLOBAL_LOCALES:
        try:
            parts[lang] = daily_reviews(app_id, since, lang, country, refresh=refresh)
        except Exception:
            failed.append(lang)
    if not parts:
        raise StoreError(t("스토어 리뷰를 가져오지 못했습니다.", "Couldn't fetch store reviews."))
    idx = pd.date_range(min(d.index.min() for d in parts.values()), max(d.index.max() for d in parts.values()), freq="D")
    out = pd.DataFrame(index=idx)
    out.index.name = "date"
    weighted = pd.Series(0.0, index=idx)
    for lang, d in parts.items():
        d = d.reindex(idx)
        out[f"rv_{lang}"] = d["reviews"].fillna(0)
        weighted += d["rating"].fillna(0) * d["reviews"].fillna(0)
    out["reviews"] = out[[c for c in out.columns if c.startswith("rv_")]].sum(axis=1)
    out["rating"] = (weighted / out["reviews"]).where(out["reviews"] > 0)
    out["reviews_ma7"] = out["reviews"].rolling(7, min_periods=1).mean()
    out.attrs["fetched_at"] = max(str(d.attrs.get("fetched_at", "")) for d in parts.values())
    return out, failed
