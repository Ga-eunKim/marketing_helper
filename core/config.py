"""앱 전역 설정: 고객사 프리셋(clients.json), URL 슬롯."""
import json
from pathlib import Path

_PRESETS = json.loads((Path(__file__).resolve().parent.parent / "clients.json").read_text(encoding="utf-8"))["clients"]

CLIENTS = list(_PRESETS)
DEFAULT_CLIENT = CLIENTS[0]  # 첫 화면 기본 고객사
# 경쟁사 선택지 = 고객사 + 각 고객사의 경쟁사 (중복 제거, 순서 유지)
COMPANIES = list(dict.fromkeys(CLIENTS + [p["competitor"] for p in _PRESETS.values() if p.get("competitor")]))

# 사이드바 고정 URL 슬롯 3개
SLOTS = [
    {"key": "main", "label": "분석 캠페인 (고객사)", "role": "고객사", "side": "고객사"},
    {"key": "competitor", "label": "경쟁사 캠페인", "role": "경쟁사", "side": "경쟁사"},
    {"key": "other", "label": "동일 소재 타 매체", "role": "타 매체", "side": "고객사"},
]


def preset(client: str) -> dict:
    """{'competitor': str, 'urls': {main, competitor, other}} — 없는 항목은 빈 값."""
    p = _PRESETS.get(client, {})
    urls = {s["key"]: p.get("urls", {}).get(s["key"], "") for s in SLOTS}
    competitor = p.get("competitor") or next(c for c in COMPANIES if c != client)
    return {"competitor": competitor, "urls": urls}
