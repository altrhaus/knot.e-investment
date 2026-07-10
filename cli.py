#!/usr/bin/env python3
"""knot.e — CLI 진입점.

사용 예:
  python cli.py doctor                          # 설정/키 점검
  python cli.py portfolio                        # 보유 종목 + 시세 + 층별 배분
  python cli.py watchlist                        # 백팀 후보 + 시세
  python cli.py analyze examples/briefing-2026-07-03.txt --date 2026-07-03
  cat briefing.txt | python cli.py analyze -     # 표준입력으로 붙여넣기
  python cli.py score LEU                        # W12 백팀 자격 채점
옵션:
  --dry-run   API 호출 없이 조립된 프롬프트만 확인 (키 없어도 동작)
  --notify    결과를 텔레그램으로 발송 (analyze)
  --json      원본 JSON 출력
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from knot.orchestrator import Orchestrator
from knot.portfolio import LAYER_NAMES
from knot.render import render_analysis, render_w12

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    _c = Console()
    RICH = True
except ImportError:  # rich 없으면 plain print
    RICH = False
    _c = None


def _print(msg=""):
    if RICH:
        _c.print(msg)
    else:
        print(msg)


def _rule(title: str):
    if RICH:
        _c.rule(f"[bold]{title}")
    else:
        print(f"\n===== {title} =====")


# ── doctor ──
def cmd_doctor(orch: Orchestrator, args):
    cfg = orch.config
    _rule("knot.e 설정 점검")
    rows = [
        ("Claude API 키", "✅ 있음" if cfg.has_claude else "❌ 없음 (.env ANTHROPIC_API_KEY)"),
        ("모델", cfg.model),
        ("텔레그램 알림", "✅ 설정됨" if cfg.has_telegram else "— 미설정(선택)"),
        ("시세 provider", cfg.market_data_provider),
        ("프레임워크 문서", f"{len(orch.kb.docs)}개" if not orch.kb.is_empty() else "❌ 없음"),
        ("보유 종목", f"{len(orch.portfolio.positions)}개"),
        ("백팀 후보", f"{len(orch.portfolio.watchlist)}개"),
    ]
    if RICH:
        t = Table(show_header=False, box=None)
        for k, v in rows:
            t.add_row(f"[cyan]{k}", str(v))
        _c.print(t)
        _c.print("\n[dim]프레임워크:[/dim] " + ", ".join(orch.kb.names()))
    else:
        for k, v in rows:
            print(f"  {k:14} {v}")
        print("  프레임워크: " + ", ".join(orch.kb.names()))
    if not cfg.has_claude:
        _print("\n[dim]※ analyze/score 는 키 없이 --dry-run 으로 파이프라인 확인 가능[/dim]"
               if RICH else "\n※ analyze/score 는 --dry-run 으로 확인 가능")


# ── portfolio ──
def cmd_portfolio(orch: Orchestrator, args):
    _rule("포트폴리오 스냅샷")
    pf = orch.portfolio_snapshot()
    by_layer: dict[int, list] = {1: [], 2: [], 3: []}
    for p in pf.positions:
        by_layer.setdefault(p.layer, []).append(p)

    for layer in sorted(by_layer):
        items = by_layer[layer]
        if not items and layer != 1:
            continue
        _print(f"\n[bold]{LAYER_NAMES.get(layer, layer)}[/bold]" if RICH else f"\n{LAYER_NAMES.get(layer, layer)}")
        if RICH:
            t = Table(box=None, pad_edge=False)
            t.add_column("티커", style="bold")
            t.add_column("현재가", justify="right")
            t.add_column("당일%", justify="right")
            t.add_column("손익%", justify="right")
            t.add_column("thesis", overflow="fold", max_width=48)
            for p in items:
                q = p.quote
                price = f"{q.price:,.2f}" if q and q.price else "—"
                chg = _pct(q.change_pct) if q else "—"
                pnl = _pct(p.pnl_pct)
                t.add_row(p.ticker, price, chg, pnl, p.thesis)
            _c.print(t)
        else:
            for p in items:
                q = p.quote
                price = f"{q.price:,.2f}" if q and q.price else "—"
                print(f"  {p.ticker:6} {price:>10}  {_pct(q.change_pct if q else None)}  {p.thesis}")

    cash = pf.cash
    _print(f"\n[dim]1층 현금: {cash.get('note','')}[/dim]" if RICH else f"\n1층 현금: {cash.get('note','')}")
    alloc = orch.config.settings.get("target_allocation", {})
    if alloc:
        _print("[dim]목표 배분(기본값): "
               f"현금 {_range(alloc.get('layer1_cash'))} · "
               f"백팀 {_range(alloc.get('layer2_backteam'))} · "
               f"청팀 {_range(alloc.get('layer3_blueteam'))}[/dim]" if RICH else "")
    if not orch.config.has_claude:
        pass
    # 시세 실패 안내
    failed = [p.ticker for p in pf.positions if p.quote and not p.quote.ok]
    if failed:
        _print(f"\n[yellow]시세 조회 실패: {', '.join(failed)} "
               f"(네트워크/티커 확인 — 로컬 실행 시 정상)[/yellow]" if RICH
               else f"\n시세 조회 실패: {', '.join(failed)}")


# ── watchlist ──
def cmd_watchlist(orch: Orchestrator, args):
    _rule("2층 백팀 후보 (watchlist)")
    market = orch.market
    if RICH:
        t = Table(box=None)
        t.add_column("티커", style="bold")
        t.add_column("현재가", justify="right")
        t.add_column("당일%", justify="right")
        t.add_column("섹터")
        t.add_column("thesis / 주의", overflow="fold", max_width=50)
        for c in orch.portfolio.watchlist:
            q = market.quote(c["ticker"])
            price = f"{q.price:,.2f}" if q.price else "—"
            note = c.get("thesis", "")
            if c.get("caution"):
                note += f"  ⚠️ {c['caution']}"
            t.add_row(c["ticker"], price, _pct(q.change_pct), c.get("sector", ""), note)
        _c.print(t)
    else:
        for c in orch.portfolio.watchlist:
            q = market.quote(c["ticker"])
            price = f"{q.price:,.2f}" if q.price else "—"
            print(f"  {c['ticker']:6} {price:>10}  {c.get('sector','')}  {c.get('thesis','')}")
    _print("\n[dim]백팀 자격 채점: python cli.py score <티커>[/dim]" if RICH
           else "\n백팀 자격 채점: python cli.py score <티커>")


# ── analyze ──
def cmd_analyze(orch: Orchestrator, args):
    briefing = _read_source(args.source, args.text)
    if not briefing.strip():
        _print("[red]브리핑 텍스트가 비어있음.[/red]" if RICH else "브리핑 텍스트가 비어있음.")
        return 1
    _rule("시황 브리핑 → 프레임워크 해석")
    result = orch.analyze_briefing(briefing, date=args.date or "", dry_run=args.dry_run,
                                   notify=args.notify)
    if args.dry_run or (not result.ok and result.prompt_system and result.data is None and not orch.config.has_claude):
        _dump_dryrun(result)
        return 0
    if not result.ok:
        _print(f"[red]분석 실패: {result.error}[/red]" if RICH else f"분석 실패: {result.error}")
        if result.raw:
            _print("[dim]원본 응답:[/dim]\n" + result.raw if RICH else "원본:\n" + result.raw)
        return 1
    if args.json:
        print(json.dumps(result.data, ensure_ascii=False, indent=2))
        return 0
    report = render_analysis(result.data)
    _print(Panel(report, title="knot.e 판단", border_style="green") if RICH else report)
    if args.notify:
        _print("\n[dim]텔레그램 발송 시도됨[/dim]" if RICH else "\n(텔레그램 발송 시도됨)")
    return 0


# ── score ──
def cmd_score(orch: Orchestrator, args):
    _rule(f"W12 백팀 자격 채점 — {args.ticker.upper()}")
    result = orch.score_ticker(args.ticker, dry_run=args.dry_run)
    if args.dry_run or (result.data is None and not orch.config.has_claude and result.error is None):
        _dump_dryrun(result)
        return 0
    if not result.ok:
        _print(f"[red]채점 실패: {result.error}[/red]" if RICH else f"채점 실패: {result.error}")
        if result.raw:
            _print(result.raw)
        return 1
    if args.json:
        print(json.dumps(result.data, ensure_ascii=False, indent=2))
        return 0
    _print(Panel(render_w12(result.data), border_style="cyan") if RICH else render_w12(result.data))
    return 0


# --- helpers ---
def _read_source(source: str | None, text: str | None) -> str:
    if text:
        return text
    if source in (None, "-"):
        if not sys.stdin.isatty():
            return sys.stdin.read()
        _print("표준입력으로 브리핑을 붙여넣고 Ctrl-D 로 종료하세요:" )
        return sys.stdin.read()
    p = Path(source)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return source  # 리터럴 텍스트로 취급


def _dump_dryrun(result):
    _print("[yellow]DRY-RUN — API 호출 없이 조립된 프롬프트만 표시[/yellow]\n" if RICH
           else "DRY-RUN — 조립된 프롬프트\n")
    _print("[bold]── SYSTEM ──[/bold]" if RICH else "── SYSTEM ──")
    _print(result.prompt_system[:2500] + ("\n...(생략)" if len(result.prompt_system) > 2500 else ""))
    _print("\n[bold]── USER ──[/bold]" if RICH else "\n── USER ──")
    _print(result.prompt_user[:2500] + ("\n...(생략)" if len(result.prompt_user) > 2500 else ""))


def _pct(v) -> str:
    if v is None:
        return "—"
    color = "green" if v >= 0 else "red"
    s = f"{v:+.2f}%"
    return f"[{color}]{s}[/{color}]" if RICH else s


def _range(r) -> str:
    if not r or len(r) != 2:
        return "—"
    return f"{r[0]*100:.0f}–{r[1]*100:.0f}%"


def main(argv=None):
    parser = argparse.ArgumentParser(prog="knot.e", description="knot.e 자산관리 오케스트레이터")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="설정/키 점검")
    sub.add_parser("portfolio", help="보유 종목 + 시세 + 층별 배분")
    sub.add_parser("watchlist", help="백팀 후보 + 시세")

    pa = sub.add_parser("analyze", help="시황 브리핑 → 프레임워크 해석")
    pa.add_argument("source", nargs="?", help="브리핑 파일 경로 또는 '-'(표준입력)")
    pa.add_argument("--text", help="브리핑 텍스트 직접 전달")
    pa.add_argument("--date", help="브리핑 날짜 (예: 2026-07-03)")
    pa.add_argument("--notify", action="store_true", help="결과를 텔레그램으로 발송")
    pa.add_argument("--dry-run", action="store_true", help="API 없이 프롬프트만 확인")
    pa.add_argument("--json", action="store_true", help="원본 JSON 출력")

    ps = sub.add_parser("score", help="W12 백팀 자격 채점")
    ps.add_argument("ticker", help="티커 (예: LEU)")
    ps.add_argument("--dry-run", action="store_true", help="API 없이 프롬프트만 확인")
    ps.add_argument("--json", action="store_true", help="원본 JSON 출력")

    args = parser.parse_args(argv)
    orch = Orchestrator.build()

    dispatch = {
        "doctor": cmd_doctor, "portfolio": cmd_portfolio, "watchlist": cmd_watchlist,
        "analyze": cmd_analyze, "score": cmd_score,
    }
    return dispatch[args.cmd](orch, args) or 0


if __name__ == "__main__":
    sys.exit(main())
