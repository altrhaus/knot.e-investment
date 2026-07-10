# 매일 리서치 자동화 (Daily Research)

knot.e의 "매일 리서치"는 두 가지 모드로 돌릴 수 있다. 핵심 분업:
- **시황/뉴스 리서치**(오늘 무슨 일이 있었나) = 웹 검색이 필요 → **Claude 에이전트**의 영역
- **정량 스캔 + 프레임워크 채점** = 앱(`quant.py` + Claude API)의 영역

---

## 모드 A — Claude(에이전트)가 매일 리서치 (권장)
스케줄 트리거가 매일 Claude 에이전트를 깨우고, 에이전트가 아래 레시피를 실행한다.
Tara의 Anthropic API 키 없이도 동작한다(에이전트가 직접 리서치·해석).

**에이전트 데일리 레시피**
1. 웹 리서치: 미국 증시 마감/매크로/보유·백팀 테마(원자력·우라늄·희토류·AI칩·금리) 뉴스 수집
2. 수집 내용을 `briefing`으로 정리
3. 정량 스캔: 보유 + 백팀 후보의 RSI/이평선/추세/트리거 (`python cli.py daily` 의 정량부)
4. 프레임워크 해석: `frameworks/` 렌즈로 정량+시황을 해석 → 데일리 리포트 생성
5. 아카이브: `research/YYYY-MM-DD.md` 로 저장 후 커밋
6. 전달: 선택한 채널(이메일/텔레그램)로 발송

**타이밍(기본 제안):** 평일(월–금) 아침. 미국장 마감(16:00 ET) 이후를 커버하도록
한국시간 오전 7–8시.

**활성화:** 트리거 1개 생성(스케줄 + 위 레시피 프롬프트). 세팅 시 knot.e 세션에서
`create_trigger`(cron: `0 22 * * 0-4` UTC = 평일 07:00 KST) 로 등록.

---

## 모드 B — 로컬에서 실행 (cron / launchd)
Tara 맥북에서 매일 아침 `daily` 를 돌린다. 시황은 붙여넣거나 정량 스캔만.

```bash
# 수동
python cli.py daily --date "$(date +%F)" --out "research/$(date +%F).md"

# 시황 붙여넣기와 함께
pbpaste | python cli.py daily - --out "research/$(date +%F).md"
```

**cron 등록(평일 07:00):**
```cron
0 7 * * 1-5  /경로/knot.e-investment/scripts/run_daily.sh >> /경로/knot.e-investment/research/cron.log 2>&1
```
`scripts/run_daily.sh` 는 venv 활성화 → `daily` 실행 → `research/날짜.md` 저장을 한다.
텔레그램 발송까지 원하면 환경변수 `KNOTE_NOTIFY=1` 로 실행.

---

## 리포트 전달 채널
| 채널 | 준비물 | 상태 |
|------|--------|------|
| 터미널/파일(`research/`) | 없음 | 즉시 |
| GitHub 레포 아카이브 | 없음(커밋) | 즉시 |
| 텔레그램 | `.env` 의 `TELEGRAM_BOT_TOKEN`,`TELEGRAM_CHAT_ID` | 토큰 발급 1분 |
| 이메일 | 메일 연동(에이전트 모드에서 발송) | 연동 시 |

---

## 리포트 형식 (예시)
```
🗞️  knot.e 데일리 리서치 — 2026-07-10

[정량 스캔 신호]
🎯 LEU: RSI 32 + 120일선 지지 — 매수 트리거 HIT
⚠️ NVDA: RSI 71 과매수, 52주 고점 부근

[보유 종목 알림] / [백팀 기회 신호] / [매크로 → 3층 구조]
...
[오늘의 우선순위 액션]
  1. LEU 1차 분할매수 검토(트리거 HIT)
[종합 판단]
...
```
