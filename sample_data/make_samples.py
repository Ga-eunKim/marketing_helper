"""샘플 CSV 생성 (가상 데이터 — 기능 시연용, 실제 성과 아님).

python sample_data/make_samples.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).parent
rng = np.random.default_rng(7)

# 1) DS-LASSO용 주간 데이터 (2024-10 ~ 2026-10, 105주)
weeks = pd.date_range("2024-10-07", "2026-10-05", freq="W-MON")
n = len(weeks)
t = np.arange(n)
temp = 14 + 11 * np.sin(2 * np.pi * (t - 15) / 52) + rng.normal(0, 2, n)
humid = 62 + 15 * np.sin(2 * np.pi * (t - 20) / 52) + rng.normal(0, 4, n)
moving = np.isin(weeks.month, [3, 4, 9, 10]).astype(float) * rng.uniform(0.8, 1.2, n)
comp_budget = 300 + 80 * rng.random(n) + 60 * moving
comp_discount = np.clip(rng.normal(10, 4, n), 0, 30)
market = 5000 + 15 * t + 400 * moving + rng.normal(0, 150, n)
yt_impr = np.where(t > 70, 900 + 300 * rng.random(n), 200 + 100 * rng.random(n)) + 0.8 * comp_budget
mall_clicks = 2000 + 1.2 * yt_impr + 3 * temp + rng.normal(0, 150, n)
sales = (800 + 0.12 * market + 0.35 * yt_impr + 0.05 * mall_clicks + 6 * temp
         - 9 * comp_discount - 0.4 * comp_budget + 120 * moving + rng.normal(0, 60, n))
pd.DataFrame({
    "date": weeks.date, "판매량": sales.round(0), "기온": temp.round(1), "습도": humid.round(1),
    "이사철지수": moving.round(2), "경쟁사_예산": comp_budget.round(0), "경쟁사_할인율": comp_discount.round(1),
    "시장_전체매출": market.round(0), "자사_캠페인노출": yt_impr.round(0), "자사몰_클릭수": mall_clicks.round(0),
}).to_csv(OUT / "sample_weekly_model.csv", index=False)

# 2) Google Ads 일별 보고서 형식 (YouTube 캠페인)
days = pd.date_range("2026-09-16", "2026-10-12")
impr = rng.integers(180_000, 260_000, len(days))
views = (impr * rng.uniform(0.18, 0.26, len(days))).astype(int)
clicks = (impr * rng.uniform(0.004, 0.007, len(days))).astype(int)
conv = (clicks * rng.uniform(0.03, 0.06, len(days))).round(1)
pd.DataFrame({
    "Day": days.strftime("%Y-%m-%d"), "Campaign": "LG전자 구독이득 대세편",
    "Impr.": impr, "Views": views, "Clicks": clicks, "Cost": (views * rng.uniform(25, 35, len(days))).round(0),
    "Conversions": conv, "Conv. value": (conv * 59000).round(0), "Currency code": "KRW",
}).to_csv(OUT / "sample_google_ads.csv", index=False)
print("written:", list(OUT.glob("*.csv")))
