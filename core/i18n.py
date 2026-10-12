"""화면 언어 (ENG/KOR). 기본 ENG — 상단 바 토글 값(session_state)을 읽는다."""
from __future__ import annotations

import re


def lang() -> str:
    try:
        import streamlit as st

        return st.session_state.get("lang", "EN")
    except Exception:  # Streamlit 밖(스크립트)에서 호출된 경우
        return "EN"


def t(ko: str, en: str) -> str:
    return en if lang() == "EN" else ko


# 화면 표기용 고정 용어
SIDE = {"고객사": "Client", "경쟁사": "Competitor"}
ROLE = {"고객사": "Client", "경쟁사": "Competitor", "타 매체": "Other channel"}
SLOT_LABEL = {
    "main": ("분석 캠페인 (고객사)", "Client campaign"),
    "competitor": ("경쟁사 캠페인", "Competitor campaign"),
    "other": ("동일 소재 타 매체", "Same creative · other channel"),
}


def side(ko: str) -> str:
    return t(ko, SIDE.get(ko, ko))


def role(ko: str) -> str:
    return t(ko, ROLE.get(ko, ko))


def slot_label(key: str) -> str:
    ko, en = SLOT_LABEL[key]
    return t(ko, en)


_REL = {"초": "second", "분": "minute", "시간": "hour", "일": "day", "주": "week", "개월": "month", "년": "year"}


def rel_time(s: str | None) -> str:
    """YouTube 한국어 상대시간('5일 전') → 'ENG 모드면 '5 days ago'."""
    if not s or lang() != "EN":
        return s or ""
    m = re.match(r"(\d+)\s*(초|분|시간|일|주|개월|년) 전", s)
    if not m:
        return s
    n, unit = int(m.group(1)), _REL[m.group(2)]
    return f"{n} {unit}{'s' if n != 1 else ''} ago"
