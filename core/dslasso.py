"""Double-Selection LASSO (Belloni, Chernozhukov & Hansen, 2014).

후보 지표 d 각각에 대해:
  1) LASSO y ~ W   (W = 통제변수 + 다른 후보 지표) 로 y 예측에 필요한 변수 선택
  2) LASSO d ~ W   로 d와 상관된 교란 변수 선택
  3) OLS  y ~ d + (1∪2 선택 변수), HC3 강건 표준오차 → d의 증분 효과·p값·95% CI
"""
from __future__ import annotations

import hashlib
from datetime import datetime

import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.linear_model import LassoCV
from sklearn.model_selection import KFold
from sklearn.preprocessing import StandardScaler
from statsmodels.stats.outliers_influence import variance_inflation_factor

from .i18n import josa, t

MIN_OBS = 20
DATE_COLS = ("date", "day", "week", "날짜", "일자", "주")


def prepare(raw: pd.DataFrame) -> pd.DataFrame | None:
    """날짜 열을 찾아 시계열 인덱스로. 날짜 열이 없으면 None."""
    date_col = next((c for c in raw.columns if c.lower() in DATE_COLS), None)
    if date_col is None:
        return None
    raw = raw.copy()
    raw[date_col] = pd.to_datetime(raw[date_col], errors="coerce")
    df = raw.dropna(subset=[date_col]).set_index(date_col).sort_index()
    df.index.name = "date"
    return df


def precheck(df: pd.DataFrame, target: str, controls: list[str], candidates: list[str]) -> tuple[list[str], list[str]]:
    """(errors, warnings). errors가 있으면 실행 불가."""
    errors, warns = [], []
    if not target:
        errors.append(t("타깃 변수를 선택하세요.", "Select a target KPI."))
    if not candidates:
        errors.append(t("후보 지표(캠페인 지표)를 1개 이상 선택하세요.", "Select at least one media driver."))
    overlap = set(candidates) & (set(controls) | {target})
    if overlap:
        errors.append(t(f"같은 변수가 여러 역할에 지정됨: {sorted(overlap)}", f"Same variable assigned to multiple roles: {sorted(overlap)}"))
    if errors:
        return errors, warns
    cols = [target] + controls + candidates
    miss = df[cols].isna().sum()
    miss = miss[miss > 0]
    if len(miss):
        warns.append(t("결측 포함 행은 제외됩니다: ", "Rows with missing values will be dropped: ")
                     + ", ".join(f"{k} {v}" for k, v in miss.items()))
    n = len(df[cols].dropna())
    p = len(controls) + len(candidates)
    if n < MIN_OBS:
        errors.append(t(f"관측치 부족: 결측 제외 {n}개 < 최소 {MIN_OBS}개", f"Not enough observations: {n} after dropping missing < minimum {MIN_OBS}"))
    elif n < 3 * p:
        warns.append(t(f"관측치({n})가 변수 수({p})의 3배 미만 — 추정이 불안정할 수 있습니다.",
                       f"Observations ({n}) are fewer than 3× the number of variables ({p}) — estimates may be unstable."))
    const = [c for c in cols if df[c].nunique(dropna=True) <= 1]
    if const:
        errors.append(t(f"값이 일정한 변수(분산 0): {const}", f"Constant variables (zero variance): {const}"))
    return errors, warns


def _lasso_select(X: pd.DataFrame, y: pd.Series, seed: int) -> list[str]:
    if X.shape[1] == 0:
        return []
    Xs = StandardScaler().fit_transform(X)
    ys = (y - y.mean()) / (y.std() or 1)
    cv = KFold(n_splits=min(5, max(3, len(y) // 10)), shuffle=True, random_state=seed)
    m = LassoCV(cv=cv, random_state=seed, max_iter=20000).fit(Xs, ys)
    return [c for c, b in zip(X.columns, m.coef_) if abs(b) > 1e-8]


def vif_table(X: pd.DataFrame) -> pd.DataFrame:
    if X.shape[1] < 2:
        return pd.DataFrame(columns=["var", "VIF"])
    Xc = sm.add_constant(X.astype(float))
    return pd.DataFrame({
        "var": X.columns,
        "VIF": [variance_inflation_factor(Xc.values, i + 1) for i in range(X.shape[1])],
    })


def input_hash(df: pd.DataFrame, target, controls, candidates) -> str:
    h = hashlib.sha1()
    h.update(pd.util.hash_pandas_object(df, index=True).values.tobytes())
    h.update(repr((target, controls, candidates)).encode())
    return h.hexdigest()[:12]


def _sig(p: float) -> str:
    return "sig05" if p < 0.05 else ("sig10" if p < 0.1 else "ns")


def run(df: pd.DataFrame, target: str, controls: list[str], candidates: list[str], seed: int = 42) -> dict:
    """결과는 언어 중립 코드로 반환 (화면에서 ENG/KOR로 표시).

    table 열: var, role(candidate|control_selected|control_dropped), direction, estimate, se, p,
              ci_lo, ci_hi, sig(sig05|sig10|ns|ref|dropped), selected
    """
    data = df[[target] + controls + candidates].dropna().astype(float)
    y = data[target]
    rows, selected_union = [], set()
    for d in candidates:
        W = data[controls + [c for c in candidates if c != d]]
        s_y = _lasso_select(W, y, seed)
        s_d = _lasso_select(W, data[d], seed)
        sel = sorted(set(s_y) | set(s_d))
        selected_union |= set(sel)
        fit = sm.OLS(y, sm.add_constant(data[[d] + sel])).fit(cov_type="HC3")
        lo, hi = fit.conf_int().loc[d]
        rows.append({"var": d, "role": "candidate", "direction": "+" if fit.params[d] > 0 else "−",
                     "estimate": fit.params[d], "se": fit.bse[d], "p": fit.pvalues[d], "ci_lo": lo, "ci_hi": hi,
                     "sig": _sig(fit.pvalues[d]), "selected": ", ".join(sel)})

    # 참고용: 선택된 통제변수 계수 (교란 보정 목적이므로 인과 해석 대상 아님)
    final_vars = candidates + sorted(selected_union - set(candidates))
    full = sm.OLS(y, sm.add_constant(data[final_vars])).fit(cov_type="HC3")
    for c in sorted(selected_union - set(candidates)):
        lo, hi = full.conf_int().loc[c]
        rows.append({"var": c, "role": "control_selected", "direction": "+" if full.params[c] > 0 else "−",
                     "estimate": full.params[c], "se": full.bse[c], "p": full.pvalues[c], "ci_lo": lo, "ci_hi": hi,
                     "sig": "ref", "selected": ""})
    for c in controls:
        if c not in selected_union:
            rows.append({"var": c, "role": "control_dropped", "direction": "", "estimate": np.nan, "se": np.nan,
                         "p": np.nan, "ci_lo": np.nan, "ci_hi": np.nan, "sig": "dropped", "selected": ""})

    return {
        "table": pd.DataFrame(rows),
        "vif": vif_table(data[final_vars]),
        "n": len(data),
        "r2": full.rsquared,
        "dw": float(sm.stats.durbin_watson(full.resid)),
        "version": input_hash(df[[target] + controls + candidates], target, controls, candidates),
        "run_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def diagnostics(res: dict) -> list[str]:
    """해석할 때 주의할 점 (현재 화면 언어로)."""
    warns = []
    high = res["vif"][res["vif"]["VIF"] > 10]
    if len(high):
        names = ", ".join(high["var"])
        vifs = ", ".join(f"{x:.1f}" for x in high["VIF"])
        warns.append(t(f"{names}{josa(names, '은/는')} 서로 많이 겹쳐서(VIF {vifs}) 각각의 효과를 깔끔하게 나누기 어렵습니다. 합쳐서 보는 편이 안전합니다.",
                       f"{names} overlap heavily (VIF {vifs}), so their separate effects are hard to tell apart. Reading them together is safer."))
    if res["n"] < 50:
        warns.append(t(f"데이터가 {res['n']}개뿐이라 결과가 크게 흔들릴 수 있습니다.",
                       f"Only {res['n']} data points, so results can swing a lot."))
    dw = res["dw"]
    if dw < 1.5 or dw > 2.5:
        warns.append(t(f"남은 오차가 시점끼리 이어지는 패턴이 보여서(Durbin-Watson {dw:.2f}) 실제보다 확실해 보일 수 있습니다.",
                       f"The leftover errors follow a pattern over time (Durbin-Watson {dw:.2f}), so results may look more certain than they are."))
    return warns


_ASSUMPTIONS_KO = """이 결과는 실험이 아니라 쌓여 있던 데이터에서 찾은 관계라서, 캠페인 때문에 판매가 늘었다고 단정할 수는 없습니다. 고른 통제변수 말고 다른 숨은 요인이 없고, 각 요인의 영향이 대체로 일정하다고 가정했습니다.

변수 선택은 데이터가 적을수록 흔들릴 수 있고, 계절성이나 광고의 이월 효과(애드스톡)는 따로 변수로 넣지 않으면 반영되지 않습니다. 확실히 하려면 지역별로 캠페인을 끄고 켜 보는 실험(지오 테스트)으로 확인하는 게 좋습니다."""

_ASSUMPTIONS_EN = """These are relationships found in historical data, not an experiment, so they don't prove the campaign caused the sales. The analysis assumes there are no hidden factors beyond the chosen controls and that each factor's effect stays roughly constant.

Variable selection can shift with small samples, and seasonality or ad carryover (adstock) isn't captured unless added as variables. A geo test — switching the campaign on and off by region — is the way to confirm."""


def assumptions() -> str:
    return t(_ASSUMPTIONS_KO, _ASSUMPTIONS_EN)
