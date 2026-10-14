"""clients.json의 모든 고객사 기본값 기준으로 데이터를 한 번 받아 디스크 캐시(data/cache/)에 저장.

python scripts/warm_cache.py      (프로젝트 루트에서 실행)
"""
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from core import cached, channel, dslasso, playstore, trends  # noqa: E402
from core import comments as cm  # noqa: E402
from core.config import category_baseline, clients, game_config, page_type, preset, promo_event  # noqa: E402

SAMPLE = Path(__file__).resolve().parent.parent / "sample_data" / "sample_weekly_model.csv"
SAMPLE_ROLES = {
    "target": "판매량",
    "controls": ["기온", "습도", "이사철지수", "경쟁사_예산", "경쟁사_할인율", "시장_전체매출"],
    "candidates": ["자사_캠페인노출", "자사몰_클릭수"],
}
COMMENT_LIMIT, COMMENT_SORT = 500, list(cm.SORTS)[0]  # 앱 기본값과 동일해야 캐시가 맞음


def step(name, fn):
    t = time.time()
    try:
        out = fn()
        print(f"✓ {name} ({time.time() - t:.1f}s)")
        return out
    except Exception as e:
        print(f"✕ {name}: {type(e).__name__}: {e}")


def warm_counterfactual(client: str, competitor: str, since):
    """'이벤트가 없었다면' 반사실 분석용 Trends (고객사+카테고리, 프로모션 키워드)."""
    found = promo_event(client, competitor)
    if not found:
        return
    for kws in ([client] + category_baseline(client), found[1]["keywords"]):
        for attempt in range(4):
            if step(f"Trends (반사실) {kws} (시도 {attempt + 1})",
                    lambda: trends.interest_over_time(kws, since, date.today(), "KR", retries=2)):
                break
            time.sleep(30)


def warm_game(client: str):
    """게임 캠페인 페이지: 링크·썸네일, 스토어 리뷰(다운로드 프록시), 검색 관심도, 트레일러 댓글."""
    cfg, p = game_config(client), preset(client)
    print(f"\n=== {client} (게임 캠페인 페이지) ===")
    w0, w1 = date.fromisoformat(cfg["campaign_start"]), date.fromisoformat(cfg["campaign_end"])
    start, end = w0 - timedelta(days=cfg.get("pre_days", 120)), w1 + timedelta(days=cfg.get("post_days", 30))
    for key, url in p["urls"].items():
        if not url:
            continue
        meta = step(f"링크 [{key}] {url}", lambda: cached.link(url, refresh=True))
        if meta and meta.get("thumbnail"):
            step(f"썸네일 [{key}]", lambda: cached.image(meta["thumbnail"]))
        existing = cached.comments_if_cached(meta["id"], cfg.get("comment_limit", 3000), "최신순") if meta else None
        if existing is not None and str(existing.attrs.get("fetched_at", "")).endswith("(CSV)"):
            print(f"    댓글: CSV로 불러온 {len(existing)}개 유지 (정확한 작성일 포함)")
        elif meta and key == "main" and meta["platform"] == "YouTube":
            df = step(f"트레일러 댓글 최신순 {cfg.get('comment_limit', 3000)}개",
                      lambda: cached.comments(meta["id"], cfg.get("comment_limit", 3000), "최신순", refresh=True))
            print(f"    → {0 if df is None else len(df)}개 수집")
    if cfg.get("store_scope") == "global":
        res = step(f"스토어 리뷰 {cfg['app_id']} 글로벌 10개 언어 ({start}~)",
                   lambda: playstore.daily_reviews_global(cfg["app_id"], start, refresh=True))
        if res is not None:
            print(f"    → {len(res[0])}일, 실패 언어: {res[1] or '없음'}")
    else:
        rv = step(f"스토어 리뷰 {cfg['app_id']} ({start}~)",
                  lambda: playstore.daily_reviews(cfg["app_id"], start, cfg.get("store_lang", "ko"), cfg.get("store_country", "kr"), refresh=True))
        if rv is not None:
            print(f"    → {len(rv)}일")
    terms = [cfg["search_term"]] + cfg.get("rival_terms", []) + ([cfg["market_term"]] if cfg.get("market_term") else [])
    for attempt in range(4):
        if step(f"Trends {terms[:5]} (시도 {attempt + 1})",
                lambda: trends.interest_over_time(terms[:5], start, end, cfg.get("geo", "KR"), retries=2)):
            break
        time.sleep(30)


def warm_client(client: str):
    if page_type(client) == "game":
        return warm_game(client)
    p = preset(client)
    print(f"\n=== {client} (경쟁사 {p['competitor']}) ===")
    since = date.today() - timedelta(days=180)
    for key, url in p["urls"].items():
        if not url:
            continue
        meta = step(f"링크 [{key}] {url}", lambda: cached.link(url, refresh=True))
        if not meta:
            continue
        if meta.get("thumbnail"):
            step(f"썸네일 [{key}]", lambda: cached.image(meta["thumbnail"]))
        if meta["platform"] == "YouTube" and meta.get("channel_id"):
            vids = step(f"채널 업로드 목록 [{key}] {meta.get('account')}",
                        lambda: channel.uploads(meta["channel_id"], since, refresh=True))
            if vids is not None:
                print(f"    → {len(vids)}개")
        if meta["platform"] == "YouTube" and meta.get("kind") != "channel":
            df = step(f"댓글 [{key}] {COMMENT_SORT} {COMMENT_LIMIT}개",
                      lambda: cached.comments(meta["id"], COMMENT_LIMIT, COMMENT_SORT, refresh=True))
            if df is not None:
                print(f"    → {len(df)}개 수집")
        if meta["platform"] == "Instagram" and meta.get("followers") is None:
            print("    ⚠️ Instagram 팔로워 수 수집 실패 (요청 제한) — 나중에 앱에서 [연동]으로 재시도")

    warm_counterfactual(client, p["competitor"], since)

    found = promo_event(client, p["competitor"])  # 메인 그래프 = 고객사·경쟁사 + 이벤트 키워드(최대 3개)
    kws = [client, p["competitor"]] + (found[1]["keywords"][:3] if found else [])
    for attempt in range(4):
        r = step(f"Google Trends {kws} (시도 {attempt + 1})",
                 lambda: trends.interest_over_time(kws, since, date.today(), "KR", retries=2))
        if r:
            break
        time.sleep(30)


def main():
    for client in clients():
        warm_client(client)

    from views.dslasso_tab import SAMPLE_EN  # ENG 화면용 변수명
    for lang, rename in [("KOR", {}), ("ENG", SAMPLE_EN)]:
        df = dslasso.prepare(pd.read_csv(SAMPLE).rename(columns=rename))
        r = {k: ([rename.get(c, c) for c in v] if isinstance(v, list) else rename.get(v, v)) for k, v in SAMPLE_ROLES.items()}
        step(f"DS-LASSO 샘플 ({lang})", lambda: cached.dsl_run(df, r["target"], r["controls"], r["candidates"], refresh=True))

if __name__ == "__main__":
    main()
