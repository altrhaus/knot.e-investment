"""knot.e Orchestrator — 도구들을 조율해 하나의 투자 판단을 만든다.

    News/브리핑 ─┐
    holdings ────┼─▶ Orchestrator ─▶ Claude(정성) ─▶ 구조화 판단 ─▶ (렌더/알림)
    market data ─┘                     W12 채점
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .analyst import Analyst, AnalystResult
from .config import Config, load_config
from .frameworks import KnowledgeBase
from .market_data import MarketData
from .notify import Notifier, NotifyResult
from .portfolio import Portfolio
from .quant import QuantEngine, TechSnapshot


@dataclass
class Orchestrator:
    config: Config
    kb: KnowledgeBase
    market: MarketData
    portfolio: Portfolio
    analyst: Analyst
    notifier: Notifier
    quant: QuantEngine

    # --- 팩토리 ---
    @classmethod
    def build(cls) -> "Orchestrator":
        cfg = load_config()
        kb = KnowledgeBase(cfg.frameworks_dir)
        market = MarketData(cfg.market_data_provider)
        portfolio = Portfolio(cfg.holdings_file, cfg.watchlist_file, market)
        analyst = Analyst(cfg.anthropic_api_key, cfg.model)
        notifier = Notifier(cfg.telegram_bot_token, cfg.telegram_chat_id)
        trig = cfg.settings.get("technical_trigger", {})
        quant = QuantEngine(market, rsi_below=trig.get("rsi_below", 35),
                            ma_support_days=trig.get("ma_support_days", 120))
        return cls(cfg, kb, market, portfolio, analyst, notifier, quant)

    # ── 시나리오 1: 포트폴리오 스냅샷 ──
    def portfolio_snapshot(self) -> Portfolio:
        self.portfolio.refresh_quotes()
        return self.portfolio

    # ── 시나리오 2: 시황 브리핑 해석 (핵심 파이프라인) ──
    def analyze_briefing(self, briefing: str, date: str = "", dry_run: bool = False,
                         notify: bool = False) -> AnalystResult:
        result = self.analyst.analyze_briefing(
            frameworks=self.kb.as_context(),
            portfolio=self.portfolio.holdings_summary(),
            briefing=briefing,
            date=date or "미상",
            dry_run=dry_run,
        )
        if notify and result.ok and result.data:
            from .render import render_analysis
            self.notifier.send(render_analysis(result.data))
        return result

    # ── 시나리오 3: 종목 리서치 (정량 기술적 + 정성 W12 통합) ──
    def research_ticker(self, ticker: str, dry_run: bool = False,
                        with_quant: bool = True) -> tuple[AnalystResult, TechSnapshot | None]:
        meta = self._lookup(ticker)
        name = meta.get("name", ticker)
        context = meta.get("sector") or meta.get("thesis") or ""
        if meta.get("thesis"):
            context = f"{context} | {meta['thesis']}" if context else meta["thesis"]
        # 정량: 펀더멘털 + 기술적
        q = self.market.quote(ticker, with_fundamentals=True)
        fundamentals = _fmt_fundamentals(q)
        snap = self.quant.snapshot(ticker) if with_quant else None
        technicals = snap.to_context() if snap else "(기술적 데이터 미포함)"
        result = self.analyst.score_w12(
            frameworks=self.kb.as_context(),
            ticker=ticker, name=name, context=context,
            fundamentals=fundamentals, technicals=technicals, dry_run=dry_run,
        )
        return result, snap

    # 하위호환 별칭 (정성 W12 위주)
    def score_ticker(self, ticker: str, dry_run: bool = False) -> AnalystResult:
        result, _ = self.research_ticker(ticker, dry_run=dry_run, with_quant=False)
        return result

    # ── 시나리오 4: 데일리 리서치 (포트폴리오 정량 스캔 + 시황 정성 해석) ──
    def quant_scan(self) -> dict[str, TechSnapshot]:
        tickers = self.portfolio.tickers() + self.portfolio.watch_tickers()
        return self.quant.scan(tickers)

    def daily_research(self, briefing: str = "", date: str = "", dry_run: bool = False,
                       notify: bool = False, snaps: dict[str, TechSnapshot] | None = None
                       ) -> tuple[AnalystResult, dict[str, TechSnapshot]]:
        snaps = snaps if snaps is not None else self.quant_scan()
        result = self.analyst.daily_research(
            frameworks=self.kb.as_context(),
            portfolio=self.portfolio.holdings_summary(),
            quant_scan=self._format_quant_scan(snaps),
            briefing=briefing, date=date or "미상", dry_run=dry_run,
        )
        if notify and result.ok and result.data:
            from .render import render_daily
            self.notifier.send(render_daily(result.data))
        return result, snaps

    def _format_quant_scan(self, snaps: dict[str, TechSnapshot]) -> str:
        holds = {t.upper() for t in self.portfolio.tickers()}
        lines = []
        for t, s in snaps.items():
            tag = "보유" if t.upper() in holds else "백팀후보"
            lines.append(f"[{tag}] {s.to_context()}")
        return "\n".join(lines) if lines else "(정량 스캔 데이터 없음)"

    # ── 알림 직접 발송 ──
    def notify(self, text: str) -> NotifyResult:
        return self.notifier.send(text)

    # --- 내부 ---
    def _lookup(self, ticker: str) -> dict[str, Any]:
        t = ticker.upper()
        for c in self.portfolio.watchlist:
            if c["ticker"].upper() == t:
                return c
        for p in self.portfolio.positions:
            if p.ticker.upper() == t:
                return {"name": p.name, "thesis": p.thesis, "sector": p.team}
        return {}


def _fmt_fundamentals(q) -> str:
    if not q.ok and q.error:
        return f"(시세/재무 조회 실패: {q.error} — 필터는 unknown 으로 두라)"
    parts = []
    if q.price is not None:
        parts.append(f"현재가: {q.price} {q.currency or ''}")
    if q.revenue_growth is not None:
        parts.append(f"매출성장률(YoY): {q.revenue_growth:.1%}")
    if q.free_cashflow is not None:
        parts.append(f"FCF: {q.free_cashflow:,.0f}")
    if q.price_to_sales is not None:
        parts.append(f"P/S: {q.price_to_sales:.2f}")
    if q.market_cap is not None:
        parts.append(f"시가총액: {q.market_cap:,.0f}")
    return "\n".join(f"- {p}" for p in parts) if parts else "(정량 데이터 없음 — 관련 필터 unknown)"
