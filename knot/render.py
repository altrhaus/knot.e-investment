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
    out = [f"🧮 종목 리서치 — {ticker}  →  W12 {score}/6  ({tier})", ""]
    out.append("[정성 — W12 백팀 자격]")
    for f in data.get("filters", []):
        mark = VERDICT_MARK.get(f.get("verdict", "unknown"), "⚠️")
        out.append(f"  {mark} {f.get('id','')} {f.get('name','')}: {f.get('reason','')}")
    if data.get("technical_read"):
        out.append("")
        out.append("[정량 — 기술적]")
        out.append(f"  {data['technical_read']}")
    if data.get("needs_check"):
        out.append("")
        out.append("확인필요: " + "; ".join(data["needs_check"]))
    combined = data.get("combined") or data.get("verdict")
    if combined:
        out.append("")
        out.append(f"🔀 통합 판단: {combined}")
    if data.get("action"):
        out.append(f"→ 액션: {data['action']}")
    return "\n".join(out)


def render_quant(snap) -> str:
    """TechSnapshot 정량 스코어카드 (Claude 없이도 표시)."""
    if not getattr(snap, "ok", False):
        return f"정량: 데이터 없음 ({getattr(snap,'error','')})"
    rows = [
        ("현재가", f"{snap.price:,.2f}" if snap.price else "—"),
        ("RSI(14)", str(snap.rsi14) if snap.rsi14 is not None else "—"),
        ("50/120/200일선", f"{_n(snap.sma50)} / {_n(snap.sma120)} / {_n(snap.sma200)}"),
        ("120일선 대비", f"{snap.pct_vs_sma120:+.1f}%" if snap.pct_vs_sma120 is not None else "—"),
        ("52주 고점대비", f"{snap.pct_off_high:+.1f}%" if snap.pct_off_high is not None else "—"),
        ("모멘텀 1M/3M", f"{_p(snap.mom_1m)} / {_p(snap.mom_3m)}"),
        ("추세", snap.trend or "—"),
    ]
    out = ["[정량 — 기술적 스코어카드]"]
    for k, v in rows:
        out.append(f"  {k:14} {v}")
    if snap.trigger_hit:
        out.append(f"  🎯 매수 트리거 HIT — {snap.trigger_desc}")
    if snap.notes:
        out.append("  · " + " · ".join(snap.notes))
    return "\n".join(out)


def render_daily(data: dict[str, Any]) -> str:
    """데일리 리서치 리포트 (정량 스캔 + 정성 해석)."""
    date = data.get("date", "")
    out = [f"🗞️  knot.e 데일리 리서치 — {date}", ""]

    qf = data.get("quant_flags") or []
    out.append("[정량 스캔 신호]")
    if qf:
        for f in qf:
            out.append(f"{f.get('signal','')} {f.get('ticker','')}: {f.get('note','')}".rstrip())
    else:
        out.append("  (특이 정량 신호 없음)")
    out.append("")

    # 정성 섹션은 analysis 렌더 재사용(같은 스키마 필드)
    body = render_analysis({
        "date": "",
        "holdings_alerts": data.get("holdings_alerts", []),
        "backteam_signals": data.get("backteam_signals", []),
        "macro": data.get("macro", []),
        "overall": "",
    }).split("\n", 2)[-1]  # 헤더 제거
    out.append(body.strip())

    pa = data.get("priority_actions") or []
    if pa:
        out.append("")
        out.append("[오늘의 우선순위 액션]")
        for i, a in enumerate(pa, 1):
            out.append(f"  {i}. {a}")
    if data.get("overall"):
        out.append("")
        out.append("[종합 판단]")
        out.append(data["overall"])
    return "\n".join(out)


def _n(v) -> str:
    return f"{v:,.2f}" if isinstance(v, (int, float)) else "—"


def _p(v) -> str:
    return f"{v:+.1f}%" if isinstance(v, (int, float)) else "—"
