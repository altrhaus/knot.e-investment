# knot.e — 자산관리 오케스트레이터 스펙

## 1. 한 줄 정의
knot.e는 **직접 만들지 않고 조율한다.** 백테스트·차트·크롤링을 스스로 하지 않고,
이미 잘하는 도구들에게 일을 시킨 뒤 결과를 모아 **윌리엄 프레임워크**로 하나의
투자 판단을 만드는 오케스트레이터다. 최종 결정은 항상 **Tara(인간)**가 한다.

## 2. 왜 오케스트레이터인가
- **재발명 안 함:** 주가 데이터·차트·실행 엔진은 이미 수백만 달러가 투입된 도구가 있다.
- **교체 가능:** 차트 도구·실행 엔진을 바꿔도 knot.e 코어 로직은 안 바뀐다.
- **고유 영역에 집중:** 프레임워크 관리 · 판단 로직 · 도구 간 조율 — 이게 knot.e만의 영역.

## 3. 아키텍처
```
                    ┌─────────────┐
                    │    Tara     │  최종 판단(승인/거부)
                    └──────┬──────┘
                    ┌──────▼──────┐
                    │   knot.e    │  조율 = 코어
                    │ Orchestrator│
                    └──────┬──────┘
        ┌─────────┬───────┼────────┬──────────┐
        ▼         ▼       ▼        ▼          ▼
   ┌────────┐┌────────┐┌──────┐┌───────┐┌──────────┐
   │Claude  ││Market  ││News  ││Notify ││(Phase4)  │
   │API     ││Data    ││입력  ││텔레그램││Quant/MCP │
   │정성판단 ││정량데이터│ 브리핑│ 알림   ││ 실행     │
   └────────┘└────────┘└──────┘└───────┘└──────────┘
```
현재 리포지토리 매핑:
| 구성요소 | 파일 | 역할 |
|----------|------|------|
| Orchestrator | `knot/orchestrator.py` | 도구 조율, 시나리오 실행 |
| 정성 판단 | `knot/analyst.py` + `knot/prompts.py` | Claude API — 뉴스 해석 / W12 채점 |
| 프레임워크 | `knot/frameworks.py` + `frameworks/` | 판단 렌즈(원칙·W12·3층·유동성지도) |
| 포트폴리오 | `knot/portfolio.py` + `data/` | holdings/watchlist 상태 |
| 정량 데이터 | `knot/market_data.py` | 시세·재무(yfinance) |
| 알림 | `knot/notify.py` | 텔레그램 |
| 렌더 | `knot/render.py` | 판단 → 리포트/알림 |
| 진입점 | `cli.py` | doctor/portfolio/watchlist/analyze/score |

## 4. 핵심 파이프라인 — "뉴스 → 프레임워크 해석 → 액션"
knot.e의 차별점. 단순 감성분석이 아니라 **Tara의 프레임워크로 뉴스를 재해석**한다.
```
시황 브리핑 텍스트
   → frameworks/ + holdings.json 을 컨텍스트로 결합
   → Claude(정성): 종목 추출 + 원칙 대입 + 3층 영향 분석
   → 구조화 JSON (holdings_alerts / backteam_signals / macro / overall)
   → 렌더 → 데일리 브리핑 리포트 (+ 선택: 텔레그램)
```
예시 입력/출력: `examples/briefing-2026-07-03.txt`, `examples/analysis-2026-07-03.sample.json`

## 5. 백팀 발굴 시나리오 (목표 워크플로우)
1. News → 에너지/원자력/희토류 뉴스에서 새 종목 감지
2. Market Data → 재무(매출성장·FCF·P/S) 수집
3. Claude → `w12-filter.md` 기준 6개 필터 채점 → "W12 5/6, Tier1, DOE 확인필요"
4. (Phase3) 기술적 매수구간 감시 → RSI 35↓ + 120일선 지지
5. Notify → Tara에게 "LEU: 백팀 Tier1, W12 5/6, RSI 32 진입 — 검토?"
6. Tara 승인 → (Phase4) 실행 엔진에 분할매수 지시

## 6. 데이터 계약
- `data/holdings.json`: 보유. `layer`(1/2/3), `team`(청팀/백팀), `shares`,`avg_price`(선택), `thesis`, `watch_principles`.
- `data/watchlist.json`: 백팀 후보. `sector`,`thesis`,`w12`(채점 캐시),`tech_trigger`,`caution`.
- `frameworks/*.md`: 판단 렌즈. '확정' 원칙만 근거로 사용, 'TODO'는 비인용.

## 7. 안전 원칙
- knot.e는 **제안**만, **결정은 Tara**.
- '확정' 프레임워크만 근거로 사용(환각·미정 원칙 인용 금지).
- 실행(Phase4)은 페이퍼 트레이딩으로 충분히 검증 후에만 실계좌 연결.

## 8. 로드맵
- **Phase 1 (완료):** 골격 — frameworks/, holdings, 시세, CLI 대시보드.
- **Phase 2 (완료):** 두뇌 — Claude 연동, 브리핑→프레임워크 해석, W12 채점.
- **Phase 3:** proactive — 텔레그램 알림 + 기술적 조건 스케줄러(RSI/이평선).
- **Phase 4 (선택):** 실행 — QuantConnect 등 MCP 실행 엔진 연동(페이퍼 후 실계좌).

## 9. MCP 진화 경로
현재는 독립 파이썬 앱이지만, 각 도구는 MCP 서버로 분리/교체 가능하도록 경계를
나눴다. Phase 4에서 QuantConnect 공식 MCP 서버를 실행 도구로, 그리고 커스텀 MCP
서버(프레임워크·포트폴리오·판단)를 knot.e 코어로 노출하는 것이 목표.
