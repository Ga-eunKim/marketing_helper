"""앱 전역 설정: 고객사 프리셋(clients.json), URL 슬롯.

clients.json은 매번 다시 읽으므로 파일을 수정하면 서버 재시작 없이 반영된다.
"""
from __future__ import annotations

import json
from pathlib import Path

CLIENTS_FILE = Path(__file__).resolve().parent.parent / "clients.json"

# 사이드바 고정 URL 슬롯 3개
SLOTS = [
    {"key": "main", "label": "분석 캠페인 (고객사)", "role": "고객사", "side": "고객사"},
    {"key": "competitor", "label": "경쟁사 캠페인", "role": "경쟁사", "side": "경쟁사"},
    {"key": "other", "label": "동일 소재 타 매체", "role": "타 매체", "side": "고객사"},
]


def presets() -> dict:
    return json.loads(CLIENTS_FILE.read_text(encoding="utf-8"))["clients"]


def clients() -> list[str]:
    """고객사 목록 — 첫 번째가 기본 고객사."""
    return list(presets())


def companies() -> list[str]:
    """경쟁사 선택지 = 고객사 + 각 고객사의 경쟁사 (중복 제거, 순서 유지)."""
    p = presets()
    return list(dict.fromkeys(list(p) + [v["competitor"] for v in p.values() if v.get("competitor")]))


def preset(client: str) -> dict:
    """{'competitor': str, 'urls': {main, competitor, other}} — 없는 항목은 빈 값."""
    p = presets().get(client, {})
    urls = {s["key"]: p.get("urls", {}).get(s["key"], "") for s in SLOTS}
    competitor = p.get("competitor") or next(c for c in companies() if c != client)
    return {"competitor": competitor, "urls": urls}


def _file() -> dict:
    return json.loads(CLIENTS_FILE.read_text(encoding="utf-8"))


def promo_event(client: str, competitor: str) -> tuple[str, dict] | None:
    """고객사 또는 경쟁사에 등록된 프로모션 이벤트 (경쟁사 우선) — (회사명, {name, name_en, keywords})."""
    events = _file().get("promo_events", {})
    for company in (competitor, client):
        if company in events:
            return company, events[company]
    return None


def category_baseline(client: str) -> list[str]:
    """반사실 분석 통제 변수(업종 카테고리 검색어) — Trends 요청당 5개 제한 때문에 최대 4개."""
    return presets().get(client, {}).get("category_baseline", [])[:4]


def name_en(company: str) -> str:
    """ENG 화면용 회사 영문명 (없으면 원래 이름)."""
    return _file().get("names_en", {}).get(company, company)


def page_type(client: str) -> str:
    """'standard' 또는 'game' (게임 캠페인 전용 페이지)."""
    return presets().get(client, {}).get("page", "standard")


def game_config(client: str) -> dict:
    return presets().get(client, {}).get("game", {})
