"""고객사 보고용 HTML 리포트 생성 + 버전/공유 링크 관리."""
from __future__ import annotations

import html
import secrets
from datetime import datetime, timedelta

import pandas as pd

from . import store

NOTE_FIELDS = ["타깃 변수", "통제변수", "후보 지표", "분석 방법", "결과 해석", "한계"]


def _table(df: pd.DataFrame) -> str:
    return df.to_html(index=False, border=0, classes="tbl", na_rep="—", float_format=lambda x: f"{x:,.4g}")


def build_html(client: str, creator: str, note: dict, sections: list[dict], sources: list[dict]) -> tuple[str, dict]:
    """sections: [{title, figs:[plotly Figure], tables:[DataFrame], text:str}]. (html, 기록 dict) 반환."""
    reports = store.load("reports", default=[])
    version = sum(1 for r in reports if r["client"] == client) + 1
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data_refreshed = max((s.get("수집 시각") or "" for s in sources), default="") or "—"
    record = {"client": client, "version": version, "creator": creator, "created_at": now,
              "data_refreshed_at": data_refreshed}

    body, plotly_loaded = [], False
    for sec in sections:
        body.append(f"<h2>{html.escape(sec['title'])}</h2>")
        if sec.get("text"):
            body.append(f"<p class='txt'>{html.escape(sec['text']).replace(chr(10), '<br>')}</p>")
        for fig in sec.get("figs", []):
            body.append(fig.to_html(full_html=False, include_plotlyjs=("inline" if not plotly_loaded else False)))
            plotly_loaded = True
        for t in sec.get("tables", []):
            body.append(_table(t))

    note_html = "".join(
        f"<dt>{html.escape(k)}</dt><dd>{html.escape(note.get(k, '') or '—').replace(chr(10), '<br>')}</dd>"
        for k in NOTE_FIELDS
    )
    src_html = _table(pd.DataFrame(sources)) if sources else "<p>—</p>"

    doc = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>{html.escape(client)} 캠페인 효과 리포트 v{version}</title>
<style>
body{{font-family:-apple-system,'Apple SD Gothic Neo','Noto Sans KR',sans-serif;margin:0;color:#1f2328;background:#fafafa}}
.wrap{{display:grid;grid-template-columns:2fr 10fr;gap:24px;max-width:1280px;margin:0 auto;padding:24px}}
.note{{background:#fff4a8;border-radius:4px;padding:16px;box-shadow:0 2px 6px rgba(0,0,0,.12);align-self:start;position:sticky;top:16px}}
.note h3{{margin-top:0}} dt{{font-weight:700;margin-top:10px}} dd{{margin:2px 0 0 0;font-size:13px}}
h1{{margin-bottom:4px}} .meta{{color:#666;font-size:13px}} h2{{border-bottom:2px solid #e5e5e5;padding-bottom:4px;margin-top:36px}}
.tbl{{border-collapse:collapse;font-size:12px;width:100%;margin:8px 0}} .tbl th,.tbl td{{border-bottom:1px solid #e5e5e5;padding:4px 6px;text-align:left}}
.tbl th{{background:#f0f0f0}} .txt{{font-size:14px;line-height:1.6}}
@media print{{.wrap{{grid-template-columns:1fr}} .note{{position:static}}}}
@media (max-width:800px){{.wrap{{grid-template-columns:1fr}}}}
</style></head><body><div class="wrap">
<aside class="note"><h3>📝 Kate's note</h3><dl>{note_html}</dl></aside>
<main><h1>{html.escape(client)} 캠페인 효과 측정·비교 리포트</h1>
<div class="meta">버전 v{version} · 생성자 {html.escape(creator)} · 생성 시각 {now} · 데이터 갱신 시각 {html.escape(data_refreshed)}</div>
{''.join(body)}
<h2>데이터 기준일 및 출처</h2>{src_html}
<p class="meta">※ 검색 관심도·댓글 반응은 매출·전환과 동일한 지표가 아니며, 회귀 결과는 인과관계를 확정하지 않습니다. PDF 저장: 브라우저 인쇄 → PDF로 저장.</p>
</main></div></body></html>"""

    store.append("reports", record)
    return doc, record


def save_report_html(client: str, version: int, doc: str) -> str:
    path = store.DATA_DIR / "reports"
    path.mkdir(parents=True, exist_ok=True)
    f = path / f"{client}_v{version}.html"
    f.write_text(doc, encoding="utf-8")
    return str(f)


def create_share(client: str, version: int, creator: str, days: int) -> dict:
    shares = store.load("shares", default={})
    token = secrets.token_urlsafe(16)
    rec = {"client": client, "version": version, "creator": creator,
           "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
           "expires_at": (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S"),
           "revoked": False}
    shares[token] = rec
    store.save("shares", shares)
    return {"token": token, **rec}


def resolve_share(token: str) -> tuple[dict | None, str | None]:
    """(share 기록, 오류 메시지)."""
    rec = store.load("shares", default={}).get(token)
    if not rec:
        return None, "존재하지 않는 공유 링크입니다."
    if rec.get("revoked"):
        return None, "공유가 해제된 링크입니다."
    if datetime.now() > datetime.strptime(rec["expires_at"], "%Y-%m-%d %H:%M:%S"):
        return None, f"만료된 링크입니다 (만료: {rec['expires_at']})."
    return rec, None


def revoke_share(token: str) -> None:
    shares = store.load("shares", default={})
    if token in shares:
        shares[token]["revoked"] = True
        store.save("shares", shares)
