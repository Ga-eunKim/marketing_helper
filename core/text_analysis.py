"""댓글 텍스트 분석: 구매 의향 / 브랜드 선호도 / 광고 메시지 연상 (한국어 사전·규칙 기반).

사전은 화면에서 수정 가능하며, 모든 지표는 '댓글 중 해당 표현이 포함된 비율'로 정의한다.
"""
from __future__ import annotations

from .i18n import t

import math
import re
from collections import Counter

import pandas as pd

DEFAULT_LEXICON = {
    "purchase": [
        "사고 싶", "사고싶", "살래", "살게", "사야겠", "살까", "사버", "샀어", "샀습니다", "샀는데",
        "구매하고 싶", "구매할", "구매했", "구매 예정", "구매각", "주문했", "주문할", "결제했", "장바구니",
        "구독했", "구독 신청", "구독신청", "신청했", "신청할", "신청하려", "가입했", "갈아타", "바꿔야", "바꿀까",
        "들여야", "상담 받아", "상담받아", "견적 받", "써보고 싶", "써보고싶", "쓰고 싶", "쓰고싶", "해야겠",
    ],
    "positive": [
        "좋", "최고", "편하", "편리", "편해", "만족", "깔끔", "안심", "추천", "감동", "멋지", "멋있", "훌륭",
        "대박", "유용", "든든", "사랑", "굿", "짱", "믿음", "신뢰", "똑똑", "부럽", "완벽", "꿀", "개이득",
        "👍", "❤", "😍", "🥰", "😊",
    ],
    "negative": [
        "별로", "비싸", "불편", "실망", "최악", "싫", "아쉽", "짜증", "고장", "불만", "거짓", "사기", "비추",
        "광고 그만", "광고충", "후회", "느려", "시끄럽", "as 안", "as안", "엉망", "호구", "👎", "😡",
    ],
}
# '좋' 앞뒤 부정 수식 → 부정으로 뒤집기 (반대로 부정어 + '없' 은 부정 취소: _negated)
NEGATION_PATTERNS = [r"안\s*좋", r"좋지\s*않", r"좋진\s*않", r"안\s*편", r"편하지\s*않", r"추천\s*안", r"만족\s*못"]

STOPWORDS = set(
    "그리고 그래서 하지만 정말 너무 진짜 이거 저거 그거 이런 저런 그런 있는 있어서 있어 없는 하는 해서 하고 합니다 "
    "같아요 같은 것 거 수 더 잘 좀 또 다 제 저 나 내 우리 저희 영상 댓글 이벤트 참여 득 득이 득입니다 득이네요 "
    "있다는 있다 있습니다 있고 하는데 해주니까 해주는 것도 것이 것을 때문에 때 가장 위해 통해 함께".split()
)


def _contains_any(text: str, words: list[str]) -> list[str]:
    t = text.lower()
    return [w for w in words if w and w.lower() in t]


def _negated(text: str, word: str, window: int = 10) -> bool:
    """'고장 걱정 없이', '불편함 없는' 처럼 부정어 뒤에 '없'이 붙어 의미가 뒤집힌 경우."""
    t = text.lower()
    return all("없" in t[i + len(word): i + len(word) + window]
               for i in [m.start() for m in re.finditer(re.escape(word.lower()), t)])


def classify(text: str, lexicon: dict, message_keywords: list[str]) -> dict:
    neg_flip = any(re.search(p, text) for p in NEGATION_PATTERNS)
    pos = _contains_any(text, lexicon["positive"])
    neg = [w for w in _contains_any(text, lexicon["negative"]) if not _negated(text, w)]
    if neg_flip:
        neg = neg + ["(부정어+긍정어)"]
        pos = [w for w in pos if w not in ("좋", "편하", "편해", "추천", "만족")]
    return {
        "purchase": bool(_contains_any(text, lexicon["purchase"])),
        "positive": len(pos) > len(neg),  # 긍·부정 표현 수가 같으면 중립
        "negative": len(neg) > len(pos),
        "message": bool(_contains_any(text, message_keywords)),
        "matched": ", ".join(sorted(set(pos + neg + _contains_any(text, lexicon["purchase"]) + _contains_any(text, message_keywords)))),
    }


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (math.nan, math.nan)
    p = k / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def apply_exclusions(
    df: pd.DataFrame,
    owner_channel_id: str | None,
    exclude_owner: bool,
    exclude_replies: bool,
    event_range: tuple | None,
    event_pattern: str | None,
) -> tuple[pd.DataFrame, list[str]]:
    """이벤트·광고주 댓글 제외. (남은 df, 제외 내역 문구 리스트) 반환."""
    log = []
    out = df.copy()
    if exclude_owner and owner_channel_id:
        from .comments import hash_channel
        m = out["channel_hash"] == hash_channel(owner_channel_id)
        log.append(t(f"광고주(채널 소유자) 댓글 {int(m.sum())}건 제외", f"Excluded {int(m.sum())} comment(s) by the advertiser (channel owner)"))
        out = out[~m]
    if exclude_replies:
        m = out["is_reply"]
        log.append(t(f"답글 {int(m.sum())}건 제외 (최상위 댓글만 사용)", f"Excluded {int(m.sum())} replies (top-level comments only)"))
        out = out[~m]
    if event_range and all(event_range):
        s, e = pd.Timestamp(event_range[0]), pd.Timestamp(event_range[1])
        m = out["date"].between(s, e)
        log.append(t(f"이벤트 기간 {s.date()}~{e.date()} 작성 댓글 {int(m.sum())}건 제외 (작성일은 YouTube 상대시간 기준 추정)",
                      f"Excluded {int(m.sum())} comment(s) posted during the event window {s.date()}–{e.date()} (post dates estimated from YouTube relative times)"))
        out = out[~m]
    if event_pattern:
        try:
            m = out["text"].str.contains(event_pattern, regex=True, na=False)
        except re.error:
            m = out["text"].str.contains(re.escape(event_pattern), regex=True, na=False)
        log.append(t(f"이벤트 응모 패턴 '{event_pattern}' 일치 댓글 {int(m.sum())}건 제외",
                      f"Excluded {int(m.sum())} comment(s) matching the contest-entry pattern '{event_pattern}'"))
        out = out[~m]
    return out, log


def analyze(df: pd.DataFrame, lexicon: dict, message_keywords: list[str]) -> tuple[dict, pd.DataFrame]:
    """지표 dict와 댓글별 분류 결과 DataFrame 반환."""
    if df.empty:
        return {"n": 0}, df
    cls = df["text"].apply(lambda t: classify(t, lexicon, message_keywords)).apply(pd.Series)
    tagged = pd.concat([df.reset_index(drop=True), cls.reset_index(drop=True)], axis=1)
    n = len(tagged)
    res = {"n": n, "date_min": tagged["date"].min(), "date_max": tagged["date"].max()}
    for key in ["purchase", "positive", "negative", "message"]:
        k = int(tagged[key].sum())
        lo, hi = wilson_ci(k, n)
        res[key] = {"k": k, "rate": k / n, "lo": lo, "hi": hi}
    res["net_preference"] = res["positive"]["rate"] - res["negative"]["rate"]
    return res, tagged


def top_terms(texts: pd.Series, n: int = 20) -> pd.DataFrame:
    c = Counter()
    for text in texts:
        for tok in re.findall(r"[가-힣A-Za-z]{2,}", text):
            if tok.lower() in STOPWORDS or tok in STOPWORDS:
                continue
            c[tok] += 1
    return pd.DataFrame(c.most_common(n), columns=[t("키워드", "Keyword"), t("빈도", "Count")])
