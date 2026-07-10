"""판단 결과(JSON)를 사람이 읽는 리포트/알림 텍스트로 렌더링."""
from __future__ import annotations

from typing import Any

VERDICT_MARK = {"pass": "✅", "fail": "❌", "unknown": "⚠️"}


def render_analysis(data: dict[str, Any]) -> str:
    """시황 분석 JSON → 데일리 브리핑 리포트 (텔레그램/터미널 공용 plain text)."""
    date = data.get("date", "")
    out: list[str] = [f"📊 knot.e 데일리 브리핑 분석 — {date}", ""]

    alerts = data.get("holdings_alerts") or []
    out.append("[보유 종목 알림]")
    if alerts:
        for a in alerts:
            head = f"{a.get('signal','')} {a.get('ticker','')}: {a.get('summary','')}".strip()
            out.append(head)
            interp = a.get("interpretation")
            pr = a.get("principle")
            pname = a.get("principle_name", "")
            if pr or interp:
                tag = f"원칙 {pr}({pname}) " if pr else ""
                out.append(f"   → {tag}{interp or ''}".rstrip())
            if a.get("action"):
                out.append(f"   → 액션: {a['action']}")
    else:
        out.append("  (해당 신호 없음)")
    out.append("")

    bt = data.get("backteam_signals") or []
    out.append("[백팀 기회 신호]")
    if bt:
        for b in bt:
            tk = f" {b['ticker']}" if b.get("ticker") else ""
            out.append(f"{b.get('signal','')}{tk} {b.get('summary','')}".rstrip())
            if b.get("action"):
                out.append(f"   → {b['action']}")
    else:
        out.append("  (해당 신호 없음)")
    out.append("")

    macro = data.get("macro") or []
    out.append("[매크로 → 3층 구조]")
    if macro:
        for m in macro:
            out.append(f"{m.get('signal','')} {m.get('summary','')}".rstrip())
            extra = " · ".join(x for x in [m.get("framework"), m.get("layer_impact")] if x)
            if extra:
                out.append(f"   → {extra}")
    else:
        out.append("  (해당 신호 없음)")
    out.append("")

    if data.get("overall"):
        out.append("[종합 판단]")
        out.append(data["overall"])
    return "\n".join(out)


def render_w12(data: dict[str, Any]) -> str:
    ticker = data.get("ticker", "")
    score = data.get("score", "?")
    tier = data.get("tier", "")
    out = [f"🧮 W12 채점 — {ticker}  →  {score}/6  ({tier})", ""]
    for f in data.get("filters", []):
        mark = VERDICT_MARK.get(f.get("verdict", "unknown"), "⚠️")
        out.append(f"  {mark} {f.get('id','')} {f.get('name','')}: {f.get('reason','')}")
    if data.get("needs_check"):
        out.append("")
        out.append("확인필요: " + "; ".join(data["needs_check"]))
    if data.get("verdict"):
        out.append("")
        out.append(f"→ {data['verdict']}")
    return "\n".join(out)
