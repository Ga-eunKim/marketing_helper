"""상단 바 URL 3개 연동: URL 검증 + 공개 메타데이터/지표 수집 (API 키 불필요).

- YouTube: oEmbed + 시청 페이지 파싱 (제목, 채널, 게시일, 조회수, 좋아요, 키워드)
- Instagram: instaloader(비로그인 공개 게시물) → 실패 시 공개 페이지 og 메타 파싱
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}
TIMEOUT = 15


class ConnectorError(Exception):
    """사용자에게 보여줄 오류 원인(cause)과 수정 방법(fix)을 담는다."""

    def __init__(self, cause: str, fix: str):
        super().__init__(cause)
        self.cause = cause
        self.fix = fix


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_url(url: str) -> tuple[str, str]:
    """(platform, id) 반환. 유효하지 않으면 ConnectorError."""
    url = (url or "").strip()
    if not url:
        raise ConnectorError("URL이 비어 있습니다.", "YouTube 영상 또는 Instagram 게시물/릴스 URL을 붙여넣으세요.")
    if not re.match(r"^https?://", url):
        url = "https://" + url
    u = urlparse(url)
    host = (u.netloc or "").lower().removeprefix("www.").removeprefix("m.")
    if not host:
        raise ConnectorError("URL 형식이 올바르지 않습니다.", "https:// 로 시작하는 전체 주소를 입력하세요.")

    if host == "youtu.be":
        vid = u.path.strip("/").split("/")[0]
    elif host.endswith("youtube.com"):
        if u.path == "/watch":
            vid = parse_qs(u.query).get("v", [""])[0]
        else:
            m = re.match(r"^/(shorts|embed|live|v)/([^/?#]+)", u.path)
            vid = m.group(2) if m else ""
    elif host.endswith("instagram.com") or host.endswith("imginn.com"):
        # imginn 등 뷰어 링크는 shortcode만 추출해 Instagram 공개 경로로 조회
        m = re.search(r"/(reel|reels|p|tv)/([A-Za-z0-9_-]+)", u.path)
        if not m:
            raise ConnectorError(
                "Instagram 게시물/릴스 주소가 아닙니다 (프로필·스토리 주소는 지원하지 않음).",
                "예: https://www.instagram.com/reel/<코드>/ 형식의 게시물 주소를 입력하세요.",
            )
        return "Instagram", m.group(2)
    else:
        raise ConnectorError(
            f"지원하지 않는 도메인입니다: {host}",
            "YouTube(youtube.com, youtu.be) 또는 Instagram(instagram.com) 주소만 연동할 수 있습니다.",
        )

    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", vid or ""):
        raise ConnectorError(
            "YouTube 영상 ID를 찾을 수 없습니다.",
            "예: https://www.youtube.com/watch?v=XXXXXXXXXXX 또는 https://youtu.be/XXXXXXXXXXX",
        )
    return "YouTube", vid


def _num(s) -> int | None:
    try:
        return int(re.sub(r"[^\d]", "", str(s)))
    except (TypeError, ValueError):
        return None


def _abbr_num(s: str | None) -> int | None:
    """'71', '1.2천', '3.4만', '1.2K' 같은 축약 수치를 정수로."""
    if not s:
        return None
    m = re.match(r"([\d.,]+)\s*(천|만|억|K|M)?", s.strip(), re.I)
    if not m:
        return None
    mult = {"천": 1e3, "만": 1e4, "억": 1e8, "k": 1e3, "m": 1e6}.get((m.group(2) or "").lower(), 1)
    return int(float(m.group(1).replace(",", "")) * mult)


def fetch_youtube(video_id: str) -> dict:
    watch_url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        oe = requests.get(
            "https://www.youtube.com/oembed",
            params={"url": watch_url, "format": "json"},
            headers=HEADERS,
            timeout=TIMEOUT,
        )
    except requests.RequestException as e:
        raise ConnectorError(f"YouTube 연결 실패: {e}", "네트워크 연결을 확인한 뒤 다시 시도하세요.")
    if oe.status_code in (401, 403):
        raise ConnectorError("비공개 또는 삽입이 제한된 영상입니다.", "공개(또는 일부 공개) 상태의 영상 URL을 사용하세요.")
    if oe.status_code == 404:
        raise ConnectorError("존재하지 않거나 삭제된 영상입니다.", "영상 ID가 정확한지 확인하세요.")
    oe.raise_for_status()
    o = oe.json()

    page = requests.get(watch_url, headers=HEADERS, timeout=TIMEOUT).text

    def grab(key):
        m = re.search(r'"%s":\s*"?([^",}]+)' % key, page)
        return m.group(1) if m else None

    kw = re.search(r'"keywords":\[([^\]]*)\]', page)
    keywords = re.findall(r'"([^"]+)"', kw.group(1)) if kw else []
    cinfo = re.search(r'"contextualInfo":\{"runs":\[\{"text":"([^"]+)"', page)
    pub = grab("publishDate") or grab("uploadDate")
    published = pub[:10] if pub else None

    return {
        "platform": "YouTube",
        "id": video_id,
        "url": watch_url,
        "title": o.get("title"),
        "account": o.get("author_name"),
        "channel_id": grab("channelId"),
        "published": published,
        "views": _num(grab("viewCount")),
        "likes": _num(grab("likeCount")),
        "comments": _abbr_num(cinfo.group(1)) if cinfo else None,  # 댓글 패널 표시값 (축약 수치일 수 있음)
        "keywords": keywords,
        "thumbnail": o.get("thumbnail_url"),
        "source": "YouTube 공개 페이지 + oEmbed",
        "fetched_at": _now(),
        "notes": [],
    }


def _caption_title(caption: str | None) -> str:
    """해시태그만 있는 줄을 건너뛴 캡션 첫 문장."""
    for line in (caption or "").split("\n"):
        text = re.sub(r"#\w+", "", line).strip(" -·")
        if len(text) >= 4:
            return text[:120]
    return ""


def _instagram_via_instaloader(shortcode: str) -> dict:
    import instaloader

    L = instaloader.Instaloader(quiet=True, max_connection_attempts=1)
    p = instaloader.Post.from_shortcode(L.context, shortcode)
    node = getattr(p, "_node", {}) or {}
    views = node.get("video_play_count") or node.get("video_view_count") or node.get("view_count")
    return {
        "title": _caption_title(p.caption) or f"Instagram {shortcode}",
        "caption": p.caption or "",
        "account": p.owner_username,
        "published": p.date_utc.replace(tzinfo=timezone.utc).astimezone().strftime("%Y-%m-%d"),
        "views": views,
        "likes": p.likes,
        "comments": p.comments,
        "keywords": list(p.caption_hashtags or []),
        "source": "Instagram 공개 게시물 (instaloader, 비로그인)",
    }


def _instagram_via_meta(shortcode: str) -> dict:
    r = requests.get(f"https://www.instagram.com/p/{shortcode}/", headers=HEADERS, timeout=TIMEOUT)
    if r.status_code == 404:
        raise ConnectorError("존재하지 않거나 삭제된 게시물입니다.", "게시물 코드가 정확한지 확인하세요.")
    metas = {}
    for tag in re.findall(r"<meta\s[^>]+>", r.text):
        k = re.search(r'(?:property|name)="([^"]+)"', tag)
        v = re.search(r'content="([^"]*)"', tag)
        if k and v:
            metas[k.group(1)] = html.unescape(v.group(1))
    desc = metas.get("og:description") or metas.get("description")
    if not desc:
        raise ConnectorError(
            "Instagram이 로그인 벽 또는 요청 제한(429)으로 공개 정보를 반환하지 않았습니다.",
            "잠시 후 [연동]을 다시 눌러 재시도하세요. 비공개 계정 게시물은 수집할 수 없습니다.",
        )
    likes = re.search(r"([\d,.]+[KkMm]?)\s*(likes|좋아요)", desc)
    comments = re.search(r"([\d,.]+[KkMm]?)\s*(comments|댓글)", desc)
    acct = re.search(r"-\s*([A-Za-z0-9_.]+)\s+(on|님)", desc)
    return {
        "title": metas.get("og:title", f"Instagram {shortcode}")[:120],
        "caption": desc,
        "account": acct.group(1) if acct else None,
        "published": None,
        "views": None,
        "likes": _num(likes.group(1)) if likes else None,
        "comments": _num(comments.group(1)) if comments else None,
        "keywords": re.findall(r"#(\w+)", desc),
        "source": "Instagram 공개 페이지 og 메타 (폴백)",
    }


def fetch_instagram(shortcode: str) -> dict:
    notes = []
    try:
        d = _instagram_via_instaloader(shortcode)
    except Exception as e:  # 로그인 벽, 429 등 → 메타 태그 폴백
        notes.append(f"instaloader 실패({type(e).__name__}) → og 메타로 대체")
        d = _instagram_via_meta(shortcode)
    if d.get("views") is None:
        notes.append("릴스 조회수는 Instagram 정책상 비로그인으로 제공되지 않아 수집 불가")
    notes.append("댓글 본문은 Instagram 로그인이 필요하여 수집 불가 (댓글 수만 표시)")
    return {
        "platform": "Instagram",
        "id": shortcode,
        "url": f"https://www.instagram.com/p/{shortcode}/",
        "channel_id": None,
        "thumbnail": None,
        "fetched_at": _now(),
        "notes": notes,
        **d,
    }


def fetch(url: str) -> dict:
    platform, ident = parse_url(url)
    if platform == "YouTube":
        return fetch_youtube(ident)
    return fetch_instagram(ident)


def default_brand_keyword(meta: dict) -> str:
    """Trends 기본 키워드: 계정/채널명 (예: 'LG전자', 'lgelectronics_kr' → 원문 유지)."""
    return (meta.get("account") or "").strip()


_PARTICLES = ("은", "는", "이", "가", "을", "를", "의", "에", "도", "로", "와", "과")


def default_message_keywords(meta: dict, limit: int = 6) -> list[str]:
    """영상 제목/캡션에서 핵심 메시지 키워드 후보 추출 (간단한 조사 제거)."""
    text = meta.get("title") or ""
    if meta.get("platform") == "Instagram":
        text = " ".join((meta.get("caption") or "").split("\n")[:4])
    tokens = re.findall(r"[가-힣A-Za-z0-9]+", text)
    out = []
    stop = {"EVENT", "LG전자", "있는", "받는", "언제인가요", "여러분에게", "가장", "같은", "것", "확인해", "주세요"}
    for t in tokens:
        if len(t) > 2 and t.endswith(_PARTICLES):
            t = t[:-1]
        if len(t) < 2 or t in stop or t.isdigit():
            continue
        if t not in out:
            out.append(t)
    return out[:limit]
