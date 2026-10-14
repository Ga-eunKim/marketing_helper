"""DS-LASSO 증분 효과 분석."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import cached, dslasso, store
from core.charts import SERIES, style
from core.i18n import josa, lang, pval, t

SAMPLE = Path(__file__).resolve().parent.parent / "sample_data" / "sample_weekly_model.csv"
# 샘플 변수명 (KOR → ENG 마케팅 용어)
SAMPLE_EN = {
    "판매량": "Sales", "기온": "Temperature", "습도": "Humidity", "이사철지수": "Moving-season index",
    "경쟁사_예산": "Competitor ad spend", "경쟁사_할인율": "Competitor discount rate",
    "시장_전체매출": "Total market sales", "자사_캠페인노출": "Campaign impressions", "자사몰_클릭수": "D2C site clicks",
}
SAMPLE_ROLES = {
    "target": "판매량",
    "controls": ["기온", "습도", "이사철지수", "경쟁사_예산", "경쟁사_할인율", "시장_전체매출"],
    "candidates": ["자사_캠페인노출", "자사몰_클릭수"],
}
ROLE_LABEL = {"candidate": ("후보 지표 (캠페인)", "Media driver"),
              "control_selected": ("통제변수 (선택됨)", "Control (selected)"),
              "control_dropped": ("통제변수 (미선택)", "Control (dropped)")}
SIG_LABEL = {"sig05": ("유의 (p<0.05)", "Significant (p<0.05)"), "sig10": ("약한 근거 (p<0.1)", "Weak evidence (p<0.1)"),
             "ns": ("유의하지 않음", "Not significant"), "ref": ("참고용 (보정 변수)", "Reference (control)"),
             "dropped": ("LASSO에서 제외", "Dropped by LASSO")}
COLS = [("var", "변수", "Variable"), ("role", "역할", "Role"), ("direction", "영향 방향", "Direction"),
        ("estimate", "효과 추정치", "Estimate"), ("se", "표준오차", "Std. error"), ("p", "p값", "p-value"),
        ("ci_lo", "95% CI 하한", "95% CI low"), ("ci_hi", "95% CI 상한", "95% CI high"),
        ("sig", "유의성", "Significance"), ("selected", "선택된 통제변수", "Selected controls")]


def _name(ko: str) -> str:
    """샘플 변수명을 현재 언어로."""
    return SAMPLE_EN.get(ko, ko) if lang() == "EN" else ko


def _load_data() -> tuple[pd.DataFrame | None, str, bool]:
    options = {"sample": t("샘플 데이터 (가상)", "Sample data (synthetic)"), "upload": t("CSV 업로드", "Upload CSV")}
    src = st.radio(t("분석 데이터", "Data source"), list(options), format_func=dict(options).get, horizontal=True, key=f"dsl_src_{lang()}")
    if src == "upload":
        # 업로더는 라벨이 바뀌면 파일이 초기화되므로 라벨은 고정하고 안내문만 번역
        st.caption(t("주/일 단위 CSV (날짜 열 + 타깃·통제·후보 지표 열)",
                     "Weekly/daily CSV (date column + target KPI, controls and media drivers)"))
        up = st.file_uploader("CSV", type=["csv"], key="dsl_up", label_visibility="collapsed")
        if up is None:
            st.caption(t("예: date, 판매량, 기온, 습도, 이사철지수, 경쟁사_예산, 경쟁사_할인율, 시장_전체매출, 자사_캠페인노출, 자사몰_클릭수",
                         "e.g. date, sales, temperature, humidity, moving_season, competitor_spend, competitor_discount, "
                         "market_sales, campaign_impressions, site_clicks"))
            return None, "", False
        try:
            return pd.read_csv(up, thousands=","), t(f"업로드: {up.name}", f"Upload: {up.name}"), False
        except Exception as e:
            st.error(t(f"CSV를 읽을 수 없습니다: {e}", f"Couldn't read the CSV: {e}"))
            st.caption(t("🔧 UTF-8 인코딩, 쉼표 구분, 첫 행 = 열 이름인지 확인하세요.",
                         "🔧 Check that it's UTF-8, comma-separated, with column names in the first row."))
            return None, "", False
    st.caption(t("샘플은 화면을 보여주기 위해 만든 가상 데이터입니다. 실제 분석은 고객사 판매 데이터를 올려서 해 주세요.",
                 "The sample is made-up data to show how this works. Upload the client's sales data for a real analysis."))
    raw = pd.read_csv(SAMPLE)
    if lang() == "EN":
        raw = raw.rename(columns=SAMPLE_EN)
    return raw, t("샘플 (가상 데이터)", "Sample (synthetic)"), True


def _display_table(table: pd.DataFrame) -> pd.DataFrame:
    out = table.copy()
    out["role"] = out["role"].map(lambda r: t(*ROLE_LABEL[r]))
    out["sig"] = out["sig"].map(lambda s: t(*SIG_LABEL[s]))
    out["selected"] = out.apply(lambda r: r["selected"] or (t("(없음)", "(none)") if r["role"] == t(*ROLE_LABEL["candidate"]) else ""),
                                axis=1)
    return out.rename(columns={k: t(ko, en) for k, ko, en in COLS})


def forest(table: pd.DataFrame) -> go.Figure:
    tb = table[table["role"] == "candidate"]
    fig = go.Figure()
    fig.add_scatter(
        x=tb["estimate"], y=tb["var"], mode="markers",
        marker=dict(size=10, color=SERIES[0]),
        error_x=dict(type="data", symmetric=False, array=tb["ci_hi"] - tb["estimate"],
                     arrayminus=tb["estimate"] - tb["ci_lo"], thickness=2, width=6),
        hovertemplate="%{y}: %{x:.4g}<extra></extra>", showlegend=False,
    )
    fig.add_vline(x=0, line=dict(color="gray", width=1, dash="dash"))
    fig.update_xaxes(title=t("증분 효과 추정치 (타깃 단위 / 후보 지표 1단위) · 95% CI",
                             "Incremental lift (target units per 1-unit increase in the driver) · 95% CI"))
    fig.update_layout(hovermode="closest")
    return style(fig, 120 + 60 * len(tb))


def render():
    st.markdown(t("#### 무엇이 판매를 끌어올렸을까 (DS-LASSO)", "#### What Actually Drove Sales? (DS-LASSO)"))
    st.caption(t("날씨, 이사철, 경쟁사 할인 같은 바깥 요인을 걸러낸 뒤 캠페인 지표가 판매에 얼마나 보탰는지 추정합니다.",
                 "Filters out outside factors like weather, moving season and competitor discounts, then estimates how much each campaign metric added to sales."))
    raw, src, is_sample = _load_data()
    if raw is None:
        return
    df = dslasso.prepare(raw)
    if df is None:
        st.error(t("날짜 열을 찾을 수 없습니다. 열 이름을 'date' 또는 '날짜'로 지정하세요.",
                   "No date column found. Name it 'date' (or '날짜')."))
        return
    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    k = lang()  # 언어별로 위젯 키를 나눠 선택지(변수명) 변경 시 충돌 방지

    st.markdown(t("**변수 고르기**", "**Choose variables**"))
    c1, c2, c3 = st.columns([2, 4, 3])
    tgt_default = _name(SAMPLE_ROLES["target"])
    target = c1.selectbox(t("타깃 변수 (판매량·전환)", "Target KPI (sales / conversions)"), num_cols,
                          index=num_cols.index(tgt_default) if is_sample and tgt_default in num_cols else 0,
                          key=f"dsl_target_{k}")
    rest = [c for c in num_cols if c != target]
    controls = c2.multiselect(t("통제변수 (기온·습도·이사철·경쟁사 예산/할인율·시장 매출 등)",
                                "Control variables (weather, seasonality, competitor spend/discounts, market size…)"), rest,
                              default=[c for c in map(_name, SAMPLE_ROLES["controls"]) if c in rest] if is_sample else [],
                              key=f"dsl_controls_{k}")
    candidates = c3.multiselect(t("후보 지표 (자사 캠페인 노출·자사몰 클릭 등)", "Media drivers (campaign impressions, site clicks…)"),
                                [c for c in rest if c not in controls],
                                default=[c for c in map(_name, SAMPLE_ROLES["candidates"]) if c in rest and c not in controls]
                                if is_sample else [],
                                key=f"dsl_candidates_{k}")
    lo, hi = df.index.min().date(), df.index.max().date()
    prev = st.session_state.get("dsl_period_val")
    value = prev if prev and lo <= prev[0] <= prev[1] <= hi else (lo, hi)
    period = st.slider(t("분석 기간", "Analysis window"), min_value=lo, max_value=hi, value=value, key=f"dsl_period_{k}")
    st.session_state.dsl_period_val = period
    sub = df.loc[str(period[0]):str(period[1])]

    st.markdown(t("**데이터 점검**", "**Data check**"))
    errors, warns = dslasso.precheck(sub, target, controls, candidates)
    for e in errors:
        st.error(e)
    for w in warns:
        st.warning(w)
    if not errors:
        n_obs = len(sub[[target] + controls + candidates].dropna())
        st.success(t(f"분석할 수 있습니다. {period[0]}부터 {period[1]}까지 {n_obs}개 시점을 씁니다.",
                     f"Ready to run — {n_obs} data points from {period[0]} to {period[1]}."))

    meta = {"target": target, "controls": controls, "candidates": candidates, "source": src,
            "period_sel": f"{period[0]} ~ {period[1]}"}
    if st.button(t("DS-LASSO 실행", "Run DS-LASSO"), type="primary", disabled=bool(errors), key="dsl_run"):
        with st.spinner(t("변수 선택 및 추정 중…", "Selecting variables and estimating…")):
            res = dict(cached.dsl_run(sub, target, controls, candidates, refresh=True), **meta)
        st.session_state.dsl = res
        prev = [r for r in store.load("runs", default=[]) if r["version"] == res["version"]]
        store.append("runs", {"version": res["version"], "run_at": res["run_at"],
                              "client": st.session_state.client, "target": target, "n": res["n"],
                              "candidates": candidates, "source": src, "period": res["period_sel"]})
        if prev:
            st.info(t(f"같은 데이터로 {len(prev) + 1}번째 실행했습니다. 실행 시각은 이력에 남겨 두었어요.",
                      f"Run #{len(prev) + 1} on the same data — logged in the run history."))
    elif not errors and (st.session_state.dsl is None or st.session_state.dsl.get("target") != target):
        hit = cached.dsl_if_cached(sub, target, controls, candidates)  # 같은 입력의 저장된 결과 자동 표시
        st.session_state.dsl = dict(hit, **meta) if hit is not None else None

    res = st.session_state.dsl
    if not res:
        return
    table = res["table"]
    st.markdown(t("**결과**", "**Results**"))
    st.plotly_chart(forest(table), use_container_width=True)
    for r in table[table["role"] == "candidate"].to_dict("records"):
        up = r["estimate"] >= 0
        verdict = {"sig05": t("믿을 만한 결과입니다", "a reliable result"),
                   "sig10": t("어느 정도 근거가 있습니다", "some evidence"),
                   "ns": t("우연일 가능성을 배제하기 어렵습니다", "could easily be chance")}.get(r["sig"], "")
        st.markdown(t(f"- **{r['var']}**{josa(r['var'], '이/가')} 1 늘 때 {res['target']}{josa(res['target'], '은/는')} 약 "
                      f"**{abs(r['estimate']):,.3g} {'늘었' if up else '줄었'}습니다** "
                      f"(95% 구간 {r['ci_lo']:,.3g} ~ {r['ci_hi']:,.3g}, p {pval(r['p'])}). {verdict}.",
                      f"- Each +1 in **{r['var']}** came with about **{abs(r['estimate']):,.3g} {'more' if up else 'less'}** {res['target']} "
                      f"(95% interval {r['ci_lo']:,.3g} to {r['ci_hi']:,.3g}, p {pval(r['p'])}) — {verdict}."))
    st.caption(t(f"관측치 {res['n']}개 · 설명력 R² {res['r2']:.2f} · 기간 {res['period_sel']} · 데이터 {res['source']} · 실행 {res['run_at']} (버전 {res['version']})",
                 f"{res['n']} data points · R² {res['r2']:.2f} · {res['period_sel']} · data: {res['source']} · run {res['run_at']} (version {res['version']})"))
    num_cfg = {t(ko, en): st.column_config.NumberColumn(format="%.4g")
               for k_, ko, en in COLS if k_ in ("estimate", "se", "p", "ci_lo", "ci_hi")}
    with st.expander(t("전체 결과 표", "Full results table")):
        st.dataframe(_display_table(table), hide_index=True, width="stretch", column_config=num_cfg)

    st.markdown(t("**해석할 때 주의할 점**", "**Things to keep in mind**"))
    for w in dslasso.diagnostics(res):
        st.warning(w)
    with st.expander(t("변수끼리 겹치는 정도 (VIF)", "How much variables overlap (VIF)")):
        st.dataframe(res["vif"].rename(columns={"var": t("변수", "Variable")}).replace([np.inf], np.nan), hide_index=True)
    st.info(dslasso.assumptions())

    with st.expander(t("실행 이력", "Run history")):
        runs = [r for r in store.load("runs", default=[]) if r.get("client") == st.session_state.client]
        st.dataframe(pd.DataFrame(runs[::-1]), hide_index=True, width="stretch")
