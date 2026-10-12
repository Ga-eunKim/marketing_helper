"""YouTube 공개 댓글 수집 (youtube-comment-downloader, API 키 불필요)."""
from __future__ import annotations

import itertools
import time
from datetime import datetime

import pandas as pd
from youtube_comment_downloader import SORT_BY_POPULAR, SORT_BY_RECENT, YoutubeCommentDownloader

SORTS = {"인기순": SORT_BY_POPULAR, "최신순": SORT_BY_RECENT}


class CommentError(Exception):
    pass


def fetch_youtube_comments(video_id: str, limit: int = 500, sort: str = "최신순", retries: int = 3) -> pd.DataFrame:
    """댓글 DataFrame 반환: cid, text, author, channel, votes, date, is_reply.

    YouTube가 간헐적으로 빈 초기 데이터를 돌려주는 경우가 있어 재시도한다.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    last_err = None
    rows: list[dict] = []
    for attempt in range(retries):
        try:
            gen = YoutubeCommentDownloader().get_comments_from_url(url, sort_by=SORTS.get(sort, SORT_BY_RECENT))
            rows = list(itertools.islice(gen, limit))
            if len(rows) > 1:
                break
        except Exception as e:  # JSON 파싱 실패, 네트워크 오류 등
            last_err = e
        time.sleep(1.5 * (attempt + 1))
    if not rows:
        if last_err:
            raise CommentError(f"댓글 수집 실패: {type(last_err).__name__}. 댓글이 비활성화되었거나 일시적 차단일 수 있습니다.")
        return pd.DataFrame(columns=["cid", "text", "author", "channel", "votes", "date", "is_reply"])

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["time_parsed"], unit="s").dt.normalize()
    df["votes"] = pd.to_numeric(df["votes"].astype(str).str.replace(r"[^\d]", "", regex=True), errors="coerce").fillna(0).astype(int)
    df["is_reply"] = df["reply"].astype(bool)
    df = df.drop_duplicates("cid")
    df.attrs["fetched_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return df[["cid", "text", "author", "channel", "votes", "date", "is_reply"]]
