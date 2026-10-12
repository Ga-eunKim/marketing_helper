"""YouTube 공개 댓글 수집 (youtube-comment-downloader, API 키 불필요)."""
from __future__ import annotations

from .i18n import t

import hashlib
import itertools
import time
from datetime import datetime

import pandas as pd
from youtube_comment_downloader import SORT_BY_POPULAR, SORT_BY_RECENT, YoutubeCommentDownloader

# 인기순은 YouTube가 일부만(또는 0개) 돌려주는 경우가 있어 최신순을 기본값으로 둔다
SORTS = {"최신순": SORT_BY_RECENT, "인기순": SORT_BY_POPULAR}


COLUMNS = ["cid", "text", "channel_hash", "votes", "date", "is_reply"]


class CommentError(Exception):
    pass


def hash_channel(channel_id: str | None) -> str | None:
    """작성자 채널 ID를 알아볼 수 없는 값으로 — 광고주 본인 댓글 판별에만 사용, 작성자 핸들은 저장하지 않음."""
    return hashlib.sha256(channel_id.encode()).hexdigest()[:16] if channel_id else None


def anonymize(df: pd.DataFrame) -> pd.DataFrame:
    """작성자 핸들 제거 + 채널 ID 해시 (이미 처리된 DataFrame은 그대로)."""
    if "channel_hash" not in df.columns:
        df = df.assign(channel_hash=df["channel"].map(hash_channel))
    return df.drop(columns=[c for c in ("author", "channel") if c in df.columns])[COLUMNS]


def fetch_youtube_comments(video_id: str, limit: int = 500, sort: str = "최신순", retries: int = 3) -> pd.DataFrame:
    """댓글 DataFrame 반환: cid, text, channel_hash, votes, date, is_reply (작성자 정보는 익명화).

    YouTube가 간헐적으로 빈 초기 데이터를 돌려주는 경우가 있어 재시도한다.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    last_err = None
    rows: list[dict] = []
    for attempt in range(retries):
        # 마지막 시도는 최신순으로 대체 (인기순이 비어 오는 경우 대비)
        sort_by = SORT_BY_RECENT if attempt == retries - 1 else SORTS.get(sort, SORT_BY_RECENT)
        try:
            gen = YoutubeCommentDownloader().get_comments_from_url(url, sort_by=sort_by)
            rows = list(itertools.islice(gen, limit))
            if len(rows) > 1:
                break
        except Exception as e:  # JSON 파싱 실패, 네트워크 오류 등
            last_err = e
        time.sleep(1.5 * (attempt + 1))
    if not rows:
        if last_err:
            raise CommentError(t(f"댓글 수집 실패: {type(last_err).__name__}. 댓글이 비활성화되었거나 일시적 차단일 수 있습니다.",
                                f"Comment collection failed: {type(last_err).__name__}. Comments may be disabled or temporarily blocked."))
        return pd.DataFrame(columns=COLUMNS)

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["time_parsed"], unit="s").dt.normalize()
    df["votes"] = pd.to_numeric(df["votes"].astype(str).str.replace(r"[^\d]", "", regex=True), errors="coerce").fillna(0).astype(int)
    df["is_reply"] = df["reply"].astype(bool)
    df = df.drop_duplicates("cid")
    df = anonymize(df)
    df.attrs["fetched_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return df
