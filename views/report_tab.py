"""⑥ 리포트 생성·공유."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from core import report as rp
from core import store
from views.common import connected_slots, slot_name

ORDER = ["overview", "trends", "dslasso", "platform", "brand"]


def _sources() -> list[dict]:
    src = []
    for s, m in connected_slots():
        src.append({"항목": slot_name(s, m), "출처": m["source"], "기준일/기간": f"게시일 {m.get('published') or '—'}",
                    "수집 시각": m["fetched_at"]})
    for k, log in st.session_state.ads_log.items():
        df = st.session_state.ads.get(k)
        if df is not None and not df.empty:
            src.append({"항목": f"Google Ads ({k})", "출처": log.get("source"),
                        "기준일/기간": f"{df['date'].min():%Y-%m-%d} ~ {df['date'].max():%Y-%m-%d}", "수집 시각": log.get("at")})
    if st.session_state.trends:
        _, meta = st.session_state.trends
        src.append({"항목": "Google Trends", "출처": meta["source"], "기준일/기간": meta["timeframe"],
                    "수집 시각": meta["fetched_at"]})
    for k, df in st.session_state.comment_data.items():
        if df is not None and len(df):
            src.append({"항목": f"YouTube 댓글 ({k})", "출처": "YouTube 공개 댓글",
                        "기준일/기간": f"{df['date'].min():%Y-%m-%d} ~ {df['date'].max():%Y-%m-%d}",
                        "수집 시각": df.attrs.get("fetched_at", "—")})
    if st.session_state.dsl:
        d = st.session_state.dsl
        src.append({"항목": f"DS-LASSO v{d['version']}", "출처": d["source"], "기준일/기간": d["period_sel"],
                    "수집 시각": d["run_at"]})
    return src


def render(note: dict):
    st.subheader("리포트 생성 및 공유")
    client, user = st.session_state.client, st.session_state.user
    parts = st.session_state.report_parts
    included = [k for k in ORDER if k in parts] + [k for k in parts if k not in ORDER]
    st.markdown("포함될 섹션: " + (", ".join(parts[k]["title"] for k in included) or "없음 — 각 탭에서 분석을 먼저 실행하세요."))
    sources = _sources()
    st.dataframe(pd.DataFrame(sources), hide_index=True, width="stretch")

    if st.button("리포트 생성", type="primary", disabled=not included, key="rp_build"):
        doc, rec = rp.build_html(client, user, note, [parts[k] for k in included], sources)
        rec["path"] = rp.save_report_html(client, rec["version"], doc)
        st.session_state.last_report = (doc, rec)
        st.success(f"v{rec['version']} 생성 완료 · {rec['created_at']}")

    if st.session_state.get("last_report"):
        doc, rec = st.session_state.last_report
        st.download_button("HTML 리포트 다운로드", doc, file_name=f"{client}_report_v{rec['version']}.html", mime="text/html")
        st.caption("PDF: 다운로드한 HTML을 브라우저에서 열고 인쇄 → 'PDF로 저장'. (차트 포함, 인쇄 레이아웃 적용)")

        st.markdown("**공유 링크 생성** (해당 고객사 리포트만 열람 가능, 만료 설정)")
        c1, c2 = st.columns([1, 3])
        days = c1.number_input("만료 (일)", 1, 90, 7, key="share_days")
        if c2.button("공유 링크 생성", key="share_make"):
            sh = rp.create_share(client, rec["version"], user, int(days))
            base = str(st.context.url).split("?")[0] if getattr(st.context, "url", None) else "http://localhost:8501/"
            st.code(f"{base}?share={sh['token']}", language=None)
            st.caption(f"만료: {sh['expires_at']}")

    reports = [r for r in store.load("reports", default=[]) if r["client"] == client]
    if reports:
        st.markdown("**리포트 이력**")
        st.dataframe(pd.DataFrame(reports[::-1]).rename(columns={
            "version": "버전", "creator": "생성자", "created_at": "생성 시각", "data_refreshed_at": "데이터 갱신 시각", "client": "고객사"}),
            hide_index=True, width="stretch")

    shares = {t: r for t, r in store.load("shares", default={}).items() if r["client"] == client}
    if shares:
        st.markdown("**공유 링크 관리**")
        for t, r in sorted(shares.items(), key=lambda x: x[1]["created_at"], reverse=True):
            c1, c2 = st.columns([5, 1])
            state = "해제됨" if r["revoked"] else f"만료 {r['expires_at']}"
            c1.caption(f"v{r['version']} · {r['creator']} · {r['created_at']} · {state} · `{t[:8]}…`")
            can = st.session_state.role == "관리자" or r["creator"] == user
            if not r["revoked"] and c2.button("해제", key=f"rv_{t}", disabled=not can):
                rp.revoke_share(t)
                st.rerun()


def render_shared(token: str):
    rec, err = rp.resolve_share(token)
    if err:
        st.error(err)
        return
    path = store.DATA_DIR / "reports" / f"{rec['client']}_v{rec['version']}.html"
    if not Path(path).exists():
        st.error("리포트 파일을 찾을 수 없습니다.")
        return
    st.caption(f"🔒 공유 리포트 (읽기 전용) · {rec['client']} v{rec['version']} · 만료 {rec['expires_at']}")
    st.components.v1.html(path.read_text(encoding="utf-8"), height=2400, scrolling=True)
