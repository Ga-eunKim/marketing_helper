"""타 플랫폼 성과 비교: 고객사 YouTube vs 고객사 Instagram (동일 소재, 링크 수집 지표)."""
from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.charts import SLOT_COLORS, style
from views.common import connected_slots, slot_name

# (지표, 표시 형식, 수집 불가 시 사유)
METRICS = [
    ("좋아요", "{:,.0f}", "좋아요 수 미제공"),
    ("댓글 수", "{:,.0f}", "댓글 수 미제공"),
    ("총 참여 (좋아요+댓글)", "{:,.0f}", "좋아요·댓글 수 미제공"),
    ("일평균 참여 (게시 후)", "{:,.1f}", "게시일 미확인"),
    ("댓글/좋아요 비율", "{:.2f}", "좋아요 수 미제공"),
    ("팔로워 대비 참여율", "{:.4%}", "팔로워(구독자) 수 수집 실패 — 잠시 후 [연동]으로 재시도"),
]


def _metrics(m: dict) -> dict:
    likes, comments = m.get("likes"), m.get("comments")
    total = (likes or 0) + (comments or 0) if likes is not None or comments is not None else None
    days = None
    if m.get("published"):
        days = max(1, (date.today() - pd.Timestamp(m["published"]).date()).days)
    followers = m.get("followers")
    return {
        "좋아요": likes,
        "댓글 수": comments,
        "총 참여 (좋아요+댓글)": total,
        "일평균 참여 (게시 후)": total / days if total is not None and days else None,
        "댓글/좋아요 비율": comments / likes if likes and comments is not None else None,
        "팔로워 대비 참여율": total / followers if total is not None and followers else None,
    }


def render():
    st.markdown("#### 타 플랫폼 성과 비교")
    own = [(s, m) for s, m in connected_slots() if s["side"] == "고객사"]
    if len({m["platform"] for _, m in own}) < 2:
        st.info("고객사 YouTube와 동일 소재 Instagram 링크가 모두 연동되어야 비교할 수 있습니다.")
        return
    st.caption("고객사 YouTube vs 고객사 Instagram (동일 소재) · 로그인 없이 공개된 지표만 사용")

    data = {slot_name(s, m): (s, m, _metrics(m)) for s, m in own}
    grid = [st.columns(3), st.columns(3)]
    for i, (metric, fmt, reason) in enumerate(METRICS):
        col = grid[i // 3][i % 3]
        fig = go.Figure()
        missing = []
        for name, (s, m, v) in data.items():
            val = v[metric]
            if val is None:
                missing.append(name)
                continue
            fig.add_bar(x=[name], y=[val], name=name, marker=dict(color=SLOT_COLORS[s["key"]], cornerradius=4),
                        text=[fmt.format(val)], textposition="outside", cliponaxis=False,
                        hovertemplate=f"{name}<br>{metric}: {fmt.format(val)}<extra></extra>")
        fig.update_layout(hovermode="closest", bargap=0.45, showlegend=False)
        if metric == "팔로워 대비 참여율":
            fig.update_yaxes(tickformat=".3%")
        style(fig, 260, metric)
        col.plotly_chart(fig, use_container_width=True)
        for name in missing:
            col.caption(f"⚠️ {name}: {reason}")

    st.caption("⚠️ 두 게시물 모두 댓글 이벤트 게시물이라 댓글 수가 자연 반응보다 부풀려져 있습니다. "
               "YouTube 구독자 수는 페이지 표시값(예: 47.8만) 기준 반올림 수치이며, 일평균은 게시일부터 오늘까지 기준입니다. "
               "조회수 기반 참여율은 Instagram 재생수를 로그인 없이 받을 수 없어 비교하지 않습니다.")
