# marketing_helper — 구글 광고 캠페인 효과 측정·비교 대시보드

기능명세서(`구글 광고 캠페인 효과 측정 및 비교 분석 대시보드_기능명세서_2026-10-12.md`) 기반 Streamlit 대시보드.

## 실행
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

## 구성
| 위치 | 내용 |
|---|---|
| 상단 바 (고정) | 사용자·고객사(미선택 시 기본 고객사)·분석 기간 + **URL 3개** (분석 캠페인 / 경쟁사 / 동일 소재 타 매체) → [연동] |
| 왼쪽 2열 | Kate's note (작성자·관리자만 수정) |
| ① 캠페인 개요 | 링크 수집 지표(조회·좋아요·댓글·게시일), 캠페인명·시작일·키워드 편집, YouTube 슬롯 한정 Google Ads CSV(선택) 정규화·중복 제거 |
| ② 검색 관심도 | pytrends 시계열 + 캠페인 시작일 원형 마커 "○○ 집행 시작", 시작 전후 비교 |
| ③ DS-LASSO | 타깃·통제·후보 지표 지정, 사전 검증, 증분 효과·95% CI, VIF·자기상관 경고, 실행 이력 |
| ④ 플랫폼·어트리뷰션 | YouTube vs Instagram 비교, 어트리뷰션 기준표, 중복 도달 반영 인사이트 |
| ⑤ 브랜드·소비자 | YouTube 공개 댓글 수집 → 구매 의향 / 선호도 / 메시지 연상 (사전 기반, 이벤트 댓글 제외) |
| ⑥ 리포트 | HTML 리포트(→ 브라우저 인쇄로 PDF), 버전·생성자·시각 기록, 만료 있는 공유 링크(`?share=`) |

## 데이터 수집 범위 (API 키 불필요)
- **YouTube**: oEmbed + 공개 페이지 (제목, 채널, 게시일, 조회수, 좋아요, 댓글 수), `youtube-comment-downloader`로 댓글 본문.
- **Instagram**: `instaloader` 비로그인 → 좋아요·댓글 수·캡션·게시일. 릴스 조회수와 댓글 본문은 로그인 필요로 **수집 불가**로 표시. imginn 링크를 넣어도 shortcode만 추출해 같은 방식으로 조회.
- **Google Trends**: pytrends (429 요청 제한 시 자동 재시도, 성공 결과는 `data/cache/`에 캐시).
- 노출·클릭·비용·전환은 링크로 얻을 수 없어 Google Ads 보고서 CSV(선택)로만 반영. 샘플 CSV는 `sample_data/` (가상 데이터).

로컬 상태(노트·실행 이력·리포트·공유 링크)는 `data/`에 JSON/HTML로 저장됩니다 (git 제외).
