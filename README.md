# knot.e 🎼

> **오케스트레이터 방식 자산관리 에이전트.**
> 뉴스·시세를 모아 **윌리엄 프레임워크**(원칙 · W12 필터 · 3층 구조)로 재해석하고,
> 실행 가능한 판단과 알림을 만든다. 최종 결정은 항상 **Tara**가 한다.

```
시황 브리핑  ─┐
holdings ────┼─▶  knot.e  ─▶  Claude(정성판단)  ─▶  데일리 브리핑 + 액션 알림
시세/재무 ───┘                 W12 백팀 채점
```

---

## 30초 요약: 지금 뭘 할 수 있나
- `python cli.py daily` → **정량 스캔 + 시황 해석을 합친 데일리 리서치** (매일 리서치)
- `python cli.py research LEU` → **정량(RSI·이평선·트리거) + 정성(W12 백팀 자격)을 통합**한 종목 판단
- `python cli.py analyze <브리핑>` → 뉴스를 프레임워크로 해석한 리포트
- `python cli.py portfolio` / `watchlist` → 보유·후보 종목 + 실시간 시세를 층별로 표시
- `python cli.py doctor` → 설정/키가 준비됐는지 점검

> **정량 + 정성을 같이 본다.** knot.e는 숫자(RSI·이평선·매출성장·FCF·P/S)와
> 프레임워크 해석(원칙·W12·3층)을 한 판단으로 합친다.
> 예: `LEU: W12 5/6(정성 Tier1) + RSI 32·120일선 지지(정량 트리거) → 분할매수 검토`

---

## 설치 (맥북 기준)

```bash
# 1) 저장소로 이동
cd knot.e-investment

# 2) 가상환경 + 의존성
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3) 키 설정
cp .env.example .env
#   .env 를 열어 ANTHROPIC_API_KEY 를 채운다 (아래 '필요한 것' 참고)

# 4) 점검
python cli.py doctor
```

> Python 3.10+ 필요. 시세는 `yfinance`(무료·키 불필요)를 쓴다.

---

## 필요한 것 (준비물)

### 필수
| 항목 | 어디서 | 비용 |
|------|--------|------|
| **Anthropic API 키** | https://console.anthropic.com → API Keys | 사용량 과금(개인 월 $5~20) — knot.e의 판단 엔진 |

`.env` 에 `ANTHROPIC_API_KEY=sk-ant-...` 만 넣으면 `analyze` / `score` 가 동작한다.

### 선택 (나중에)
| 항목 | 용도 | 비용 |
|------|------|------|
| Telegram Bot 토큰 | 폰 알림 (Phase 3) | 무료 (@BotFather) |
| Finnhub/Polygon 키 | 더 정밀한 시세/뉴스 자동수집 | 무료 티어~$29/월 |
| QuantConnect 계정 | 백테스트·실행 (Phase 4) | 무료 티어~ |

### 콘텐츠 (Tara만 할 수 있는 것 — 가장 중요)
knot.e의 판단 품질 = 프레임워크 품질. `frameworks/` 를 채우고 다듬는 게 핵심 작업이다.
- `frameworks/william-principles.md` — 원칙 25~48 중 **확정 4개(33·34·45·46)만 채워져 있음.** 나머지는 TODO.
- `frameworks/w12-filter.md` — 6필터 **초안.** 윌리엄 원문 정의가 있으면 교체.
- `data/holdings.json` — 보유 종목의 `shares`/`avg_price` 는 **직접 입력**(현재 null).

---

## 사용법

```bash
# 설정 점검
python cli.py doctor

# 포트폴리오 / 백팀 후보 (실시간 시세)
python cli.py portfolio
python cli.py watchlist

# ── 매일 리서치 (정량 스캔 + 시황 해석) ──
python cli.py daily                                  # 정량 스캔만으로도 동작
python cli.py daily examples/briefing-2026-07-03.txt --date 2026-07-10
pbpaste | python cli.py daily - --notify --out output/2026-07-10.txt

# ── 종목 리서치 (정량 기술적 + 정성 W12 통합) ──
python cli.py research LEU
python cli.py research BWXT --json

# ── 핵심: 시황 브리핑 해석 ──
python cli.py analyze examples/briefing-2026-07-03.txt --date 2026-07-03
pbpaste | python cli.py analyze -            # (맥: 클립보드를 바로)

# 키 없이 파이프라인만 확인 (정량 스캔 + 프롬프트 조립 검증)
python cli.py daily --dry-run
python cli.py research LEU --dry-run
```

`analyze` 출력 예시 (형식): `examples/analysis-2026-07-03.sample.json` 참고. 실제 리포트는
`[보유 종목 알림] / [백팀 기회 신호] / [매크로 → 3층 구조] / [종합 판단]` 구조로 나온다.

---

## 프로젝트 구조
```
knot.e-investment/
├── cli.py                  # 진입점 (doctor/portfolio/watchlist/analyze/research/daily)
├── knot/                   # 오케스트레이터 코어
│   ├── orchestrator.py     #   도구 조율
│   ├── analyst.py          #   Claude 판단 엔진
│   ├── prompts.py          #   프레임워크 주입 프롬프트
│   ├── frameworks.py       #   frameworks/ 로더
│   ├── portfolio.py        #   holdings/watchlist
│   ├── market_data.py      #   시세/재무/가격히스토리 (yfinance)
│   ├── quant.py            #   정량 엔진 — RSI·이평선·추세·매수트리거
│   ├── notify.py           #   텔레그램
│   └── render.py           #   판단 → 리포트
├── frameworks/             # ★ 판단 렌즈 (원칙·W12·3층·유동성지도)
├── data/                   # holdings.json / watchlist.json
├── config/settings.json    # 목표배분·모델·기술적트리거
├── examples/               # 샘플 브리핑 + 출력
├── SPEC.md                 # 아키텍처/비전
└── .env.example            # 키 템플릿
```

---

## 로드맵
- ✅ **Phase 1** 골격 — frameworks/ · holdings · 시세 · CLI
- ✅ **Phase 2** 두뇌 — Claude 연동 · 브리핑→프레임워크 해석 · W12 채점
- ✅ **Phase 2.5** 정량+정성 — 정량 엔진(RSI·이평선·트리거) · `research` 통합 판단 · `daily` 데일리 리서치
- 🚧 **Phase 3** proactive — 텔레그램 알림 + **매일 리서치 자동 실행**(스케줄 트리거)
- ⬜ **Phase 4** 실행 — QuantConnect(MCP) 연동, 페이퍼 검증 후 실계좌

## 원칙
knot.e는 **제안**하고 **Tara가 결정**한다. 확정된 프레임워크만 근거로 쓰며,
미정(TODO) 원칙은 인용하지 않는다. 실제 자금 실행은 충분한 페이퍼 검증 후에만.
