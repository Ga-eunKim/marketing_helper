"""앱 전역 설정: 고객사 프리셋(clients.json), URL 슬롯.

clients.json은 매번 다시 읽으므로 파일을 수정하면 서버 재시작 없이 반영된다.
"""
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
