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


@dataclass
class Orchestrator:
    config: Config
    kb: KnowledgeBase
    market: MarketData
    portfolio: Portfolio
    analyst: Analyst
    notifier: Notifier

    # --- 팩토리 ---
    @classmethod
    def build(cls) -> "Orchestrator":
        cfg = load_config()
        kb = KnowledgeBase(cfg.frameworks_dir)
        market = MarketData(cfg.market_data_provider)
        portfolio = Portfolio(cfg.holdings_file, cfg.watchlist_file, market)
        analyst = Analyst(cfg.anthropic_api_key, cfg.model)
        notifier = Notifier(cfg.telegram_bot_token, cfg.telegram_chat_id)
        return cls(cfg, kb, market, portfolio, analyst, notifier)

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

    # ── 시나리오 3: W12 백팀 자격 채점 ──
    def score_ticker(self, ticker: str, dry_run: bool = False) -> AnalystResult:
        # watchlist/holdings 에서 메타 찾기
        meta = self._lookup(ticker)
        name = meta.get("name", ticker)
        context = meta.get("sector") or meta.get("thesis") or ""
        if meta.get("thesis"):
            context = f"{context} | {meta['thesis']}" if context else meta["thesis"]
        # 정량 데이터 수집 (도구 호출)
        q = self.market.quote(ticker, with_fundamentals=True)
        fundamentals = _fmt_fundamentals(q)
        return self.analyst.score_w12(
            frameworks=self.kb.as_context(),
            ticker=ticker, name=name, context=context,
            fundamentals=fundamentals, dry_run=dry_run,
        )

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
