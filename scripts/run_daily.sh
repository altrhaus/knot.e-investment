#!/usr/bin/env bash
# knot.e 로컬 데일리 리서치 실행기 (cron/launchd 용).
#   crontab 예) 0 7 * * 1-5  /path/knot.e-investment/scripts/run_daily.sh >> /path/knot.e-investment/research/cron.log 2>&1
# 사용법: run_daily.sh [브리핑파일]   (브리핑 생략 시 정량 스캔 위주로 동작)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# venv 활성화(있으면)
if [ -f ".venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

DATE="$(date +%F)"
mkdir -p research

ARGS=(daily --date "$DATE" --out "research/${DATE}.md")
# 첫 인자가 존재하는 파일이면 시황 브리핑으로 전달
if [ -n "${1:-}" ] && [ -f "$1" ]; then
  ARGS=(daily "$1" --date "$DATE" --out "research/${DATE}.md")
fi
# KNOTE_NOTIFY=1 이면 텔레그램 발송
if [ "${KNOTE_NOTIFY:-}" = "1" ]; then
  ARGS+=(--notify)
fi

echo "[$(date)] knot.e daily research → research/${DATE}.md"
python cli.py "${ARGS[@]}"
