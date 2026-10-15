"""탭 간 공유 상태 헬퍼."""
from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from core import cached, i18n
from core import url_connector as uc
from core.config import SLOTS, clients, preset
from core.i18n import t


def init_state():
    ss = st.session_state
    client = ss.get("client_sel") or clients()[0]
    if "urls" not in ss or ss.get("preset_applied") != preset(client):
        apply_preset(client)  # 첫 실행이거나 clients.json이 바뀐 경우 다시 매핑
    ss.setdefault("slots", {})          # key -> meta dict | {"error":..., "fix":...}
    ss.setdefault("comment_data", {})   # key -> 수집 댓글 DataFrame
    ss.setdefault("trends", None)       # (df, meta)
    ss.setdefault("dsl", None)
    ss.setdefault("period", (date.today() - timedelta(days=180), date.today()))


def apply_preset(client: str):
    """고객사 선택 시 경쟁사·URL을 프리셋으로 채우고 이전 고객사의 결과를 비운다 (다음 실행에서 자동 연동)."""
    ss = st.session_state
    p = preset(client)
    ss.preset_applied = p
    ss.urls = dict(p["urls"])
    for k, v in p["urls"].items():
        ss[f"url_{k}"] = v  # 사이드바 입력칸 값도 함께 교체
    ss.competitor = ss["competitor_sel"] = p["competitor"]
    ss.slots, ss.comment_data = {}, {}
    ss.trends, ss.trends_err, ss.trends_auto, ss.dsl = None, None, False, None
    ss.connected = False


def connect_all(force: bool = False):
    ss = st.session_state
    main_msg = None
    for s in SLOTS:
        url = (ss.urls.get(s["key"]) or "").strip()
        prev = ss.slots.get(s["key"]) or {}
        if not url:
            ss.slots[s["key"]] = None
            continue
        try:
            meta = dict(cached.link(url, refresh=force))
        except uc.ConnectorError as e:
            ss.slots[s["key"]] = {"error": e.cause, "fix": e.fix, "url": url}
            continue
        except Exception as e:  # 예상 못 한 네트워크/파싱 오류
            ss.slots[s["key"]] = {"error": f"{type(e).__name__}: {e}", "fix": t("잠시 후 [연동]을 다시 눌러 재시도하세요.", "Click [Connect] again shortly."), "url": url}
            continue
        meta["published"] = uc.iso_date(meta.get("published"))  # 예전에 캐시된 잘못된 날짜 값 정리
        same = prev.get("id") == meta["id"]
        meta["campaign_name"] = prev.get("campaign_name") if same else (meta.get("title") or "")[:40]
        meta["start_date"] = prev.get("start_date") if same else meta.get("published")
        msg = ", ".join(uc.default_message_keywords(meta))
        if s["key"] == "other" and main_msg:
            msg = main_msg  # 동일 소재 → 같은 핵심 메시지
        if s["key"] == "main":
            main_msg = msg
        meta["msg_kw"] = prev.get("msg_kw") if same else msg
        ss.slots[s["key"]] = meta
    ss.connected = True


def connected_slots(platform: str | None = None) -> list[tuple[dict, dict]]:
    """[(slot_def, meta)] — 연동 성공한 슬롯만."""
    out = []
    for s in SLOTS:
        m = st.session_state.slots.get(s["key"])
        if m and "error" not in m and (platform is None or m["platform"] == platform):
            out.append((s, m))
    return out


def slot_name(s: dict, m: dict) -> str:
    """화면 표기용 라벨: 'Client YouTube' / '고객사 YouTube' 등."""
    return f"{i18n.side(s['side'])} {m['platform']}"


def image_bytes(url: str) -> bytes | None:
    """썸네일을 서버에서 받아 전달 (Instagram CDN 핫링크·만료 회피, 디스크 캐시)."""
    return cached.image(url)


def kw_list(s: str) -> list[str]:
    return [k.strip() for k in (s or "").replace("\n", ",").split(",") if k.strip()]
