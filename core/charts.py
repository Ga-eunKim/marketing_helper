"""차트 공통 스타일 (검증된 categorical 팔레트, 엔터티 고정 색상)."""
from __future__ import annotations

import plotly.graph_objects as go

# 고정 순서 (dataviz reference palette, light)
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
SLOT_COLORS = {"main": SERIES[0], "competitor": SERIES[1], "other": SERIES[2]}
GRID = "rgba(128,128,128,0.18)"


def style(fig: go.Figure, height: int = 380, title: str | None = None) -> go.Figure:
    fig.update_layout(
        height=height,
        title=dict(text=title or ""),  # None이면 Streamlit에서 'undefined'로 표시되므로 빈 문자열
        margin=dict(l=10, r=10, t=50 if title else 20, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        hovermode="x unified",
        font=dict(family="-apple-system, 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif", size=12),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_xaxes(showgrid=False, linecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    return fig
