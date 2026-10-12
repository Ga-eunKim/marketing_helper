"""상단 바 URL 3개 연동: URL 검증 + 공개 메타데이터/지표 수집 (API 키 불필요).

- YouTube: oEmbed + 시청 페이지 파싱 (제목, 채널, 게시일, 조회수, 좋아요, 키워드)
- Instagram: instaloader(비로그인 공개 게시물) → 실패 시 공개 페이지 og 메타 파싱
"""
from __future__ import annotations

from .i18n import t

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
        raise ConnectorError(t("URL이 비어 있습니다.", "The URL is empty."), t("YouTube 영상 또는 Instagram 게시물/릴스 URL을 붙여넣으세요.", "Paste a YouTube video or Instagram post/Reel URL."))
    if not re.match(r"^https?://", url):
        url = "https://" + url
    u = urlparse(url)
    host = (u.netloc or "").lower().removeprefix("www.").removeprefix("m.")
    if not host:
        raise ConnectorError(t("URL 형식이 올바르지 않습니다.", "Invalid URL format."), t("https:// 로 시작하는 전체 주소를 입력하세요.", "Enter the full address starting with https://."))

    if host == "youtu.be":
        vid = u.path.strip("/").split("/")[0]
    elif host.endswith("youtube.com"):
        ch = re.match(r"^/(@[^/?#]+|channel/UC[\w-]{22})", u.path)
        if ch:  # 채널 URL (@핸들 또는 /channel/UC…)
            return "YouTubeChannel", ch.group(1)
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
                t("Instagram 게시물/릴스 주소가 아닙니다 (프로필·스토리 주소는 지원하지 않음).",
                  "Not an Instagram post/Reel URL (profile and Story URLs aren't supported)."),
                t("예: https://www.instagram.com/reel/<코드>/ 형식의 게시물 주소를 입력하세요.",
                  "Use a post URL like https://www.instagram.com/reel/<code>/."),
            )
        return "Instagram", m.group(2)
    else:
        raise ConnectorError(
            t(f"지원하지 않는 도메인입니다: {host}", f"Unsupported domain: {host}"),
            t("YouTube 영상·채널(youtube.com, youtu.be) 또는 Instagram(instagram.com) 주소만 연동할 수 있습니다.",
              "Only YouTube video/channel (youtube.com, youtu.be) or Instagram (instagram.com) URLs are supported."),
        )

    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", vid or ""):
        raise ConnectorError(
            t("YouTube 영상 ID를 찾을 수 없습니다.", "Couldn't find a YouTube video ID."),
            t("예: https://www.youtube.com/watch?v=XXXXXXXXXXX 또는 https://youtu.be/XXXXXXXXXXX",
              "e.g. https://www.youtube.com/watch?v=XXXXXXXXXXX or https://youtu.be/XXXXXXXXXXX"),
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
        raise ConnectorError(t(f"YouTube 연결 실패: {e}", f"Couldn't reach YouTube: {e}"),
                             t("네트워크 연결을 확인한 뒤 다시 시도하세요.", "Check your network connection and try again."))
    if oe.status_code in (401, 403):
        raise ConnectorError(t("비공개 또는 삽입이 제한된 영상입니다.", "This video is private or embedding is restricted."),
                             t("공개(또는 일부 공개) 상태의 영상 URL을 사용하세요.", "Use a public or unlisted video URL."))
    if oe.status_code == 404:
        raise ConnectorError(t("존재하지 않거나 삭제된 영상입니다.", "The video doesn't exist or was removed."),
                             t("영상 ID가 정확한지 확인하세요.", "Double-check the video ID."))
    oe.raise_for_status()
    o = oe.json()

    page = requests.get(watch_url, headers=HEADERS, timeout=TIMEOUT).text
    if "ytInitialPlayerResponse" not in page:  # 'unusual traffic' 차단 페이지 등
        raise ConnectorError(t("YouTube가 일시적으로 요청을 제한했습니다 (비정상 트래픽 감지).",
                               "YouTube is temporarily rate-limiting requests (unusual traffic detected)."),
                             t("몇 분~1시간 뒤 [연동]을 다시 누르세요. 이전에 수집한 값이 있으면 그 값을 계속 사용합니다.",
                               "Click [Connect] again in a few minutes to an hour. Previously collected data stays in use."))

    def grab(key):
        m = re.search(r'"%s":\s*"?([^",}]+)' % key, page)
        return m.group(1) if m else None

    kw = re.search(r'"keywords":\[([^\]]*)\]', page)
    keywords = re.findall(r'"([^"]+)"', kw.group(1)) if kw else []
    cinfo = re.search(r'"contextualInfo":\{"runs":\[\{"text":"([^"]+)"', page)
    subs = re.search(r'"subscriberCountText":.{0,200}?"simpleText":"(?:구독자\s*)?([\d.,]+\s*[천만억KM]?)', page)
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
        "followers": _abbr_num(subs.group(1)) if subs else None,  # 구독자 수 (표시값 반올림, 예: 47.8만)
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
        "thumbnail": p.url,
        "source": "Instagram 공개 게시물 (instaloader, 비로그인)",
    }


def _instagram_via_meta(shortcode: str) -> dict:
    r = requests.get(f"https://www.instagram.com/p/{shortcode}/", headers=HEADERS, timeout=TIMEOUT)
    if r.status_code == 404:
        raise ConnectorError(t("존재하지 않거나 삭제된 게시물입니다.", "The post doesn't exist or was removed."),
                             t("게시물 코드가 정확한지 확인하세요.", "Double-check the post code."))
    metas = {}
    for tag in re.findall(r"<meta\s[^>]+>", r.text):
        k = re.search(r'(?:property|name)="([^"]+)"', tag)
        v = re.search(r'content="([^"]*)"', tag)
        if k and v:
            metas[k.group(1)] = html.unescape(v.group(1))
    desc = metas.get("og:description") or metas.get("description")
    if not desc:
        raise ConnectorError(
            t("Instagram이 로그인 벽 또는 요청 제한(429)으로 공개 정보를 반환하지 않았습니다.",
              "Instagram returned no public data (login wall or rate limit 429)."),
            t("잠시 후 [연동]을 다시 눌러 재시도하세요. 비공개 계정 게시물은 수집할 수 없습니다.",
              "Click [Connect] again shortly. Posts from private accounts can't be collected."),
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
        "thumbnail": metas.get("og:image"),
        "source": "Instagram 공개 페이지 og 메타 (폴백)",
    }


def _instagram_followers(username: str | None) -> int | None:
    """계정 팔로워 수 — instaloader → 프로필 페이지 og 메타 순으로 시도, 실패 시 None (요청 제한이 잦음)."""
    if not username:
        return None
    try:
        import instaloader

        L = instaloader.Instaloader(quiet=True, max_connection_attempts=1)
        return instaloader.Profile.from_username(L.context, username).followers
    except Exception:
        pass
    try:
        r = requests.get(f"https://www.instagram.com/{username}/", headers=HEADERS, timeout=TIMEOUT)
        m = re.search(r'content="([\d.,]+\s*[KkMm천만]?)\s*(?:Followers|팔로워)', r.text) or \
            re.search(r'팔로워\s*([\d.,]+\s*[천만]?)', r.text)
        return _abbr_num(m.group(1)) if m else None
    except requests.RequestException:
        return None


def fetch_instagram(shortcode: str) -> dict:
    notes = []
    try:
        d = _instagram_via_instaloader(shortcode)
    except Exception as e:  # 로그인 벽, 429 등 → 메타 태그 폴백
        notes.append(f"instaloader 실패({type(e).__name__}) → og 메타로 대체")
        d = _instagram_via_meta(shortcode)
    d["followers"] = _instagram_followers(d.get("account"))
    if d["followers"] is None:
        notes.append("팔로워 수 수집 실패 (Instagram 요청 제한) — 잠시 후 [연동]으로 재시도")
    if d.get("views") is None:
        notes.append("릴스 조회수는 Instagram 정책상 비로그인으로 제공되지 않아 수집 불가")
    notes.append("댓글 본문은 Instagram 로그인이 필요하여 수집 불가 (댓글 수만 표시)")
    return {
        "platform": "Instagram",
        "id": shortcode,
        "url": f"https://www.instagram.com/p/{shortcode}/",
        "channel_id": None,
        "fetched_at": _now(),
        "notes": notes,
        **d,
    }


def fetch_youtube_channel(path: str) -> dict:
    """채널 URL → 채널 정보 (영상 단위 지표 없음). path = '@핸들' 또는 'channel/UC…'."""
    url = f"https://www.youtube.com/{path}/videos"
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise ConnectorError(t(f"YouTube 연결 실패: {e}", f"Couldn't reach YouTube: {e}"),
                             t("네트워크 연결을 확인한 뒤 다시 시도하세요.", "Check your network connection and try again."))
    if r.status_code == 404:
        raise ConnectorError(t("존재하지 않는 채널입니다.", "The channel doesn't exist."),
                             t("채널 주소(@핸들)가 정확한지 확인하세요.", "Double-check the channel handle (@handle)."))
    page = r.text
    cid = re.search(r'"externalId":"(UC[\w-]{22})"', page)
    if not cid:
        raise ConnectorError(t("YouTube 채널 정보를 읽지 못했습니다 (일시 차단 또는 구조 변경).",
                               "Couldn't read the YouTube channel (temporary block or page change)."),
                             t("몇 분 뒤 [연동]을 다시 누르세요.", "Click [Connect] again in a few minutes."))

    def meta(prop):
        m = re.search(r'<meta property="og:%s" content="([^"]*)"' % prop, page)
        return html.unescape(m.group(1)) if m else None

    subs = re.search(r"구독자\s*([\d.,]+\s*[천만억]?)명", page)
    name = meta("title") or path
    return {
        "platform": "YouTube",
        "kind": "channel",
        "id": cid.group(1),
        "url": f"https://www.youtube.com/{path}",
        "title": f"{name} 채널",
        "account": name,
        "channel_id": cid.group(1),
        "published": None,
        "views": None,
        "likes": None,
        "comments": None,
        "followers": _abbr_num(subs.group(1)) if subs else None,
        "keywords": [],
        "thumbnail": meta("image"),
        "source": "YouTube 채널 페이지",
        "fetched_at": _now(),
        "notes": ["채널 URL — 영상 단위 지표(조회수·좋아요·댓글)는 없고, 검색 관심도 그래프의 업로드 점으로만 사용"],
    }


def fetch(url: str) -> dict:
    platform, ident = parse_url(url)
    if platform == "YouTube":
        return fetch_youtube(ident)
    if platform == "YouTubeChannel":
        return fetch_youtube_channel(ident)
    return fetch_instagram(ident)


_PARTICLES = ("은", "는", "이", "가", "을", "를", "의", "에", "도", "로", "와", "과")


def default_message_keywords(meta: dict, limit: int = 6) -> list[str]:
    """영상 제목/캡션에서 핵심 메시지 키워드 후보 추출 (간단한 조사 제거)."""
    text = meta.get("title") or ""
    if meta.get("platform") == "Instagram":
        text = " ".join((meta.get("caption") or "").split("\n")[:4])
    tokens = re.findall(r"[가-힣A-Za-z0-9]+", text)
    out = []
    stop = {"EVENT", "LG전자", "있는", "받는", "언제인가요", "여러분에게", "가장", "같은", "것", "확인해", "주세요"}
    for tok in tokens:
        if len(tok) > 2 and tok.endswith(_PARTICLES):
            tok = tok[:-1]
        if len(tok) < 2 or tok in stop or tok.isdigit():
            continue
        if tok not in out:
            out.append(tok)
    return out[:limit]
