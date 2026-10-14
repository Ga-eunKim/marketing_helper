"""게임 캠페인 페이지 계산: 댓글 테마(세계관·구매/복귀 의도) 점수, 캠페인 건강도, SOS 시차 분석.

LLM 대신 편집 가능한 한·영 키워드 사전으로 분류한다 (API 키 없이 클라우드에서 동작). 점수 정의는
화면 설명 카드와 같다.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

# 테마 → {표시 키워드: [매칭 표현(소문자, 부분 일치)]}
THEMES: dict[str, dict[str, list[str]]] = {
    "lore": {
        "Shadow Milk": ["shadow milk", "shadowmilk", "쉐도우밀크", "섀도우밀크", "쉐도우 밀크"],
        "Beast Cookies": ["beast", "비스트"],
        "Story / Lore": ["lore", "story", "storyline", "스토리", "세계관", "떡밥"],
        "Truth & Deceit": ["truth", "deceit", "lie", "liar", "진실", "거짓"],
        "Anniversary": ["anniversary", "4th", "4주년", "주년"],
        "Ancients": ["ancient", "pure vanilla", "hollyberry", "dark cacao", "golden cheese", "white lily",
                     "고대", "퓨어바닐라", "홀리베리", "다크카카오", "골든치즈", "화이트릴리"],
        "Mystic Flour / Eternal Sugar": ["mystic flour", "eternal sugar", "silent salt", "burning spice",
                                         "미스틱플라워", "이터널슈가", "사일런트솔트", "버닝스파이스"],
        "Carnival / Jester": ["carnival", "jester", "joker", "카니발", "광대"],
        "Theory": ["theory", "theories", "foreshadow", "추측", "복선"],
    },
    "intent": {
        "Returning": ["came back", "coming back", "returning", "return to", "back to the game", "reinstall",
                      "복귀", "다시 시작", "재설치"],
        "Spending": ["spend", "wallet", "money", "buy", "purchase", "pay", "지갑", "현질", "과금", "결제"],
        "Pulling": ["pull", "gacha", "crystal", "summon", "뽑기", "가챠", "크리스탈", "뽑"],
        "Downloading": ["download", "install", "start playing", "다운", "설치", "시작했"],
    },
    "general": {
        "Cute": ["cute", "adorable", "baby", "귀엽", "귀여"],
        "Love / Fun": ["love", "fun", "amazing", "awesome", "best", "재밌", "좋아", "최고"],
        "Animation / Art": ["animation", "art", "visual", "design", "작화", "연출", "그림"],
        "Music / Voice": ["music", "song", "ost", "voice", "노래", "음악", "성우"],
    },
    "negative": {
        "Gacha rates": ["rates", "rigged", "unlucky", "확률", "창렬"],
        "Bugs / Lag": ["bug", "lag", "crash", "glitch", "버그", "렉", "튕"],
        "Pay-to-win": ["p2w", "pay to win", "pay2win", "cash grab", "과금 유도", "돈겜"],
        "Disappointed": ["boring", "disappointed", "worst", "hate", "실망", "노잼", "별로"],
    },
}
THEME_LABEL = {"lore": ("세계관 몰입", "Lore"), "intent": ("구매·복귀 의도", "Purchase / return intent"),
               "general": ("일반 반응", "General"), "negative": ("부정", "Negative")}


def _pattern(words: list[str]) -> re.Pattern:
    """영문 표현은 단어 앞 경계에서만 매칭('art'가 start·heart에, 'ost'가 most에 걸리지 않게),
    한글은 부분 일치 (조사가 붙어도 매칭)."""
    parts = [(r"(?<![a-z])" + re.escape(w)) if w.isascii() else re.escape(w) for w in words]
    return re.compile("|".join(parts))


def _hits(text: str, pattern: re.Pattern) -> bool:
    return bool(pattern.search(text.lower()))


def classify(comments: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """댓글별 테마 플래그와 테마·키워드별 언급 수."""
    texts = comments["text"].fillna("").astype(str)
    flags = pd.DataFrame(index=comments.index)
    counts = []
    for theme, kws in THEMES.items():
        theme_any = pd.Series(False, index=comments.index)
        for label, words in kws.items():
            pat = _pattern(words)
            hit = texts.map(lambda x, pt=pat: _hits(x, pt))
            theme_any |= hit
            counts.append({"theme": theme, "keyword": label, "count": int(hit.sum())})
        flags[theme] = theme_any
    n = len(comments)
    thematic = int(flags.any(axis=1).sum())
    scores = {
        "n": n,
        "thematic": thematic,
        # 세계관 몰입도 = 테마가 감지된 댓글 중 세계관 언급 비율 (0–100)
        "lore": 100 * flags["lore"].sum() / thematic if thematic else np.nan,
        # 구매·복귀 의도 = 전체 댓글 중 구매/복귀 의도 표현 비율 (0–100)
        "intent": 100 * flags["intent"].sum() / n if n else np.nan,
        "negative": 100 * flags["negative"].sum() / n if n else np.nan,
    }
    return pd.DataFrame(counts), scores


def hook_score(views, likes, comments, benchmark: float = 0.04) -> tuple[float | None, float | None]:
    """Hook Rate 프록시 = 참여율((좋아요+댓글)/조회수). 점수 = 참여율 / 벤치마크(4%) × 100, 상한 100."""
    if not views:
        return None, None
    er = ((likes or 0) + (comments or 0)) / views
    return er, min(100.0, er / benchmark * 100)


def health_index(lore: float, intent: float, hook: float | None) -> float:
    """캠페인 건강도 = 세계관 몰입도 40% + 구매·복귀 의도(×5, 상한 100) 30% + Hook 점수 30%."""
    intent_s = min(100.0, (intent or 0) * 5)
    parts = [(lore or 0, 0.4), (intent_s, 0.3)]
    if hook is not None:
        parts.append((hook, 0.3))
    w = sum(p[1] for p in parts)
    return sum(v * k for v, k in parts) / w


def zone(score: float) -> str:
    return "high" if score > 70 else ("moderate" if score > 30 else "low")


def iroas_rating(rel_effect: float, p: float) -> str:
    """지출 데이터가 없어 금액 iROAS 대신 증분 크기·유의성 기반 등급."""
    if p < 0.05 and rel_effect > 0.2:
        return "high"
    if rel_effect > 0 and (p < 0.1 or rel_effect > 0.1):
        return "moderate"
    return "low"


def sos(trends_df: pd.DataFrame, own: str, rivals: list[str]) -> pd.Series:
    """Share of Search = 자사 / (자사 + 경쟁작) 검색 관심도."""
    cols = [own] + [r for r in rivals if r in trends_df.columns]
    total = trends_df[cols].sum(axis=1).replace(0, np.nan)
    return (trends_df[own] / total).rename("sos")


def lag_corr(x: pd.Series, y: pd.Series, max_lag: int = 21) -> pd.DataFrame:
    """x(t−lag)와 y(t)의 상관 — 검색이 리뷰 유입을 며칠 앞서는지."""
    rows = []
    for lag in range(0, max_lag + 1):
        pair = pd.concat([x.shift(lag), y], axis=1).dropna()
        if len(pair) > 10:
            rows.append({"lag": lag, "corr": float(pair.iloc[:, 0].corr(pair.iloc[:, 1]))})
    return pd.DataFrame(rows)
