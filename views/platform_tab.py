"""타 플랫폼 성과 비교: 고객사 YouTube vs 고객사 Instagram (동일 소재, 링크 수집 지표)."""
from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.charts import SLOT_COLORS, style
from core.i18n import t
from views.common import connected_slots, slot_name

# (내부 키, KOR 표기, ENG 표기, 표시 형식, KOR 수집 불가 사유, ENG 수집 불가 사유)
METRICS = [
    ("likes", "좋아요", "Likes", "{:,.0f}", "좋아요 수 미제공", "Likes not available"),
    ("comments", "댓글 수", "Comments", "{:,.0f}", "댓글 수 미제공", "Comment count not available"),
    ("total", "총 참여 (좋아요+댓글)", "Total engagements (likes + comments)", "{:,.0f}",
     "좋아요·댓글 수 미제공", "Likes/comments not available"),
    ("daily", "일평균 참여 (게시 후)", "Avg. daily engagements (since posting)", "{:,.1f}",
     "게시일 미확인", "Post date unknown"),
    ("ratio", "댓글/좋아요 비율", "Comment-to-like ratio", "{:.2f}", "좋아요 수 미제공", "Likes not available"),
    ("er", "팔로워 대비 참여율", "Engagement rate by followers", "{:.4%}",
     "팔로워(구독자) 수 수집 실패 — 잠시 후 [연동]으로 재시도",
     "Follower/subscriber count unavailable — click [Connect] again later"),
]


def _metrics(m: dict) -> dict:
    likes, comments = m.get("likes"), m.get("comments")
    total = (likes or 0) + (comments or 0) if likes is not None or comments is not None else None
    days = None
    published = pd.to_datetime(m.get("published"), errors="coerce")  # 날짜가 아니면 NaT → 일평균만 생략
    if pd.notna(published):
        days = max(1, (date.today() - published.date()).days)
    followers = m.get("followers")
    return {
        "likes": likes,
        "comments": comments,
        "total": total,
        "daily": total / days if total is not None and days else None,
        "ratio": comments / likes if likes and comments is not None else None,
        "er": total / followers if total is not None and followers else None,
    }


def render():
    st.markdown(t("#### 유튜브와 인스타그램, 어디서 더 반응했을까", "#### YouTube vs. Instagram"))
    own = [(s, m) for s, m in connected_slots() if s["side"] == "고객사"]
    if len({m["platform"] for _, m in own}) < 2:
        st.info(t("고객사 유튜브 영상과 같은 소재의 인스타그램 링크를 둘 다 넣어야 비교할 수 있습니다.",
                  "Add both the client's YouTube video and the same creative on Instagram to compare."))
        return

    data = {slot_name(s, m): (s, m, _metrics(m)) for s, m in own}
    grid = [st.columns(3), st.columns(3)]
    for i, (key, ko, en, fmt, reason_ko, reason_en) in enumerate(METRICS):
        col, label = grid[i // 3][i % 3], t(ko, en)
        fig = go.Figure()
        missing = []
        for name, (s, m, v) in data.items():
            val = v[key]
            if val is None:
                missing.append(name)
                continue
            fig.add_bar(x=[name], y=[val], name=name, marker=dict(color=SLOT_COLORS[s["key"]], cornerradius=4),
                        text=[fmt.format(val)], textposition="outside", cliponaxis=False,
                        hovertemplate=f"{name}<br>{label}: {fmt.format(val)}<extra></extra>")
        fig.update_layout(hovermode="closest", bargap=0.45, showlegend=False)
        if key == "er":
            fig.update_yaxes(tickformat=".3%")
        style(fig, 260, label)
        col.plotly_chart(fig, use_container_width=True)
        for name in missing:
            col.caption(f"⚠️ {name}: {t(reason_ko, reason_en)}")

    st.caption(t("댓글 이벤트를 한 게시물은 댓글 수가 평소보다 많게 나올 수 있습니다. 구독자 수는 '47.8만'처럼 반올림된 표시값이고, "
                 "일평균은 게시일부터 오늘까지로 계산했습니다. 인스타그램 재생수는 로그인 없이 볼 수 없어 조회수 기준 참여율은 비교하지 않았습니다.",
                 "Posts with comment contests can show more comments than usual. Subscriber counts are rounded display values, and daily "
                 "averages run from the post date to today. Instagram plays need a login, so view-based engagement isn't compared."))
