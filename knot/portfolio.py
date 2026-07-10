"""포트폴리오 상태 — holdings.json / watchlist.json 로드 및 시세 결합."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .market_data import MarketData, Quote

LAYER_NAMES = {1: "1층 현금", 2: "2층 백팀", 3: "3층 청팀"}


@dataclass
class Position:
    ticker: str
    name: str
    layer: int
    team: str
    role: str = ""
    shares: float | None = None
    avg_price: float | None = None
    thesis: str = ""
    watch: str = ""
    watch_principles: list[str] = field(default_factory=list)
    quote: Quote | None = None

    @property
    def market_value(self) -> float | None:
        if self.shares and self.quote and self.quote.price:
            return self.shares * self.quote.price
        return None

    @property
    def pnl_pct(self) -> float | None:
        if self.avg_price and self.quote and self.quote.price:
            return round((self.quote.price - self.avg_price) / self.avg_price * 100, 2)
        return None


class Portfolio:
    def __init__(self, holdings_file: Path, watchlist_file: Path, market: MarketData):
        self.holdings_file = holdings_file
        self.watchlist_file = watchlist_file
        self.market = market
        self._raw = _load_json(holdings_file)
        self._watch_raw = _load_json(watchlist_file)
        self.positions = [
            Position(
                ticker=p["ticker"], name=p.get("name", p["ticker"]),
                layer=p.get("layer", 3), team=p.get("team", ""),
                role=p.get("role", ""), shares=p.get("shares"),
                avg_price=p.get("avg_price"), thesis=p.get("thesis", ""),
                watch=p.get("watch", ""), watch_principles=p.get("watch_principles", []),
            )
            for p in self._raw.get("positions", [])
        ]

    @property
    def cash(self) -> dict[str, Any]:
        return self._raw.get("cash", {})

    @property
    def watchlist(self) -> list[dict[str, Any]]:
        return self._watch_raw.get("candidates", [])

    def tickers(self) -> list[str]:
        return [p.ticker for p in self.positions]

    def watch_tickers(self) -> list[str]:
        return [c["ticker"] for c in self.watchlist]

    def refresh_quotes(self) -> None:
        """보유 종목 시세를 일괄 갱신."""
        quotes = self.market.quotes(self.tickers())
        for p in self.positions:
            p.quote = quotes.get(p.ticker)

    def holdings_summary(self) -> str:
        """Claude 컨텍스트용 간결한 보유/관심 요약 텍스트."""
        lines = ["[보유 종목]"]
        for p in self.positions:
            lines.append(
                f"- {p.ticker} ({p.name}) | {LAYER_NAMES.get(p.layer, p.layer)}/{p.team}"
                f" | thesis: {p.thesis}"
                + (f" | 주시: {p.watch}" if p.watch else "")
                + (f" | 관련원칙: {','.join(p.watch_principles)}" if p.watch_principles else "")
            )
        lines.append("\n[백팀 후보 (watchlist)]")
        for c in self.watchlist:
            lines.append(
                f"- {c['ticker']} ({c.get('name','')}) | {c.get('sector','')}"
                f" | thesis: {c.get('thesis','')}"
                + (f" | 주의: {c.get('caution')}" if c.get("caution") else "")
            )
        return "\n".join(lines)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
