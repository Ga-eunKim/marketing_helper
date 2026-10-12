"""YouTube 채널 업로드 영상 목록 (API 키 불필요).

채널 '동영상' 탭 목록 페이지만 읽는다 (영상별 페이지 요청 없음 → YouTube 차단 방지).
업로드일은 목록에 표시된 상대시간('5일 전', '2개월 전')으로 추정하므로 주·개월 단위는 오차가 있다.
Shorts·라이브 탭은 포함하지 않는다.
"""
from __future__ import annotations

from .i18n import t

import json
import re
from datetime import date, timedelta

import requests

from . import cache
from .url_connector import HEADERS, TIMEOUT

REL_DAYS = {"초": 0, "분": 0, "시간": 0, "일": 1, "주": 7, "개월": 30, "년": 365}


class ChannelError(Exception):
    pass


def _walk(o):
    if isinstance(o, dict):
        if "lockupViewModel" in o:
            yield "video", o["lockupViewModel"]
        elif "continuationItemRenderer" in o:
            yield "next", o["continuationItemRenderer"]
        else:
            for v in o.values():
                yield from _walk(v)
    elif isinstance(o, list):
        for x in o:
            yield from _walk(x)


def _parse(data) -> tuple[list[dict], str | None]:
    videos, tokens = [], []
    for kind, v in _walk(data):
        if kind == "video":
            md = v.get("metadata", {}).get("lockupMetadataViewModel", {})
            rel = re.search(r"(\d+)\s*(초|분|시간|일|주|개월|년) 전", json.dumps(md, ensure_ascii=False))
            videos.append({
                "id": v.get("contentId"),
                "title": md.get("title", {}).get("content", ""),
                "rel": rel.group(0) if rel else None,
                "approx_days": int(rel.group(1)) * REL_DAYS[rel.group(2)] if rel else None,
            })
        else:
            tok = v.get("continuationEndpoint", {}).get("continuationCommand", {}).get("token")
            if tok:
                tokens.append(tok)
    # 정렬 칩(최신/인기/오래된 순) 토큰은 짧고, 다음 페이지 토큰이 가장 길다
    return [x for x in videos if x["id"]], max(tokens, key=len) if tokens else None


def _list(channel_id: str, since: date, max_pages: int = 20) -> list[dict]:
    s = requests.Session()
    s.headers.update(HEADERS)
    html = s.get(f"https://www.youtube.com/channel/{channel_id}/videos", timeout=TIMEOUT).text
    try:
        key = re.search(r'"INNERTUBE_API_KEY":"([^"]+)"', html).group(1)
        ver = re.search(r'"INNERTUBE_CLIENT_VERSION":"([^"]+)"', html).group(1)
        data = json.loads(re.search(r"var ytInitialData = (\{.*?\});</script>", html, re.S).group(1))
    except (AttributeError, json.JSONDecodeError):
        raise ChannelError(t("채널 페이지 구조를 읽을 수 없습니다 (YouTube 구조 변경 또는 일시 차단).",
                             "Couldn't parse the channel page (YouTube layout change or temporary block)."))
    window = (date.today() - since).days
    videos, tok = _parse(data)
    for _ in range(max_pages):
        if not tok or any((v["approx_days"] or 0) > window for v in videos[-30:]):
            break
        r = s.post(f"https://www.youtube.com/youtubei/v1/browse?key={key}", timeout=TIMEOUT, json={
            "context": {"client": {"clientName": "WEB", "clientVersion": ver, "hl": "ko", "gl": "KR"}},
            "continuation": tok})
        more, tok = _parse(r.json())
        if not more:
            break
        videos += more
    today = date.today()
    out = []
    for v in videos:
        if v["approx_days"] is None or v["approx_days"] > (today - since).days:
            continue
        out.append({"id": v["id"], "title": v["title"], "rel": v["rel"],
                    "published": (today - timedelta(days=v["approx_days"])).isoformat(),  # 추정일
                    "url": f"https://www.youtube.com/watch?v={v['id']}"})
    return sorted(out, key=lambda x: x["published"])


def uploads(channel_id: str, since: date, refresh: bool = False) -> list[dict]:
    """분석 시작일 이후 업로드된 영상 [{id, title, published, url}].

    채널별로 최근 1년치를 하루 단위로 캐시하고 기간은 읽을 때 거른다 — 날짜가 바뀌어도 캐시를 재사용하고,
    새로 받기에 실패하면(클라우드 IP 차단 등) 마지막으로 받은 목록을 그대로 쓴다.
    """
    year_ago = date.today() - timedelta(days=365)
    vids = cache.cached("uploads_ch", channel_id, lambda: _list(channel_id, min(since, year_ago)), cache.DAY, refresh)
    return [v for v in vids if v["published"] >= since.isoformat()]
