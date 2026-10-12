"""링크 수집 지표를 매체 공통 스키마로 표준화."""
from __future__ import annotations


def link_metrics_row(slot_label: str, meta: dict) -> dict:
    views, likes, comments = meta.get("views"), meta.get("likes"), meta.get("comments")
    eng = (likes or 0) + (comments or 0)
    return {
        "슬롯": slot_label,
        "매체": meta.get("platform"),
        "캠페인명": meta.get("campaign_name") or meta.get("title"),
        "계정": meta.get("account"),
        "시작일": meta.get("start_date") or meta.get("published"),
        "조회수": views,
        "좋아요": likes,
        "댓글 수": comments,
        "참여율": (eng / views) if views else None,
        "데이터 출처": meta.get("source"),
        "수집 시각": meta.get("fetched_at"),
    }
