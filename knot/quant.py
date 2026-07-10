"""정량 분석 엔진 — 가격 히스토리에서 기술적 지표를 계산한다.

지표 계산은 순수 함수(closes 리스트 입력)로 분리해 네트워크 없이도 검증 가능하다.
데이터 수집은 QuantEngine 이 MarketData(yfinance)를 통해 한다.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any


# ─────────────────────── 순수 지표 함수 ───────────────────────
def sma(closes: list[float], window: int) -> float | None:
    if len(closes) < window:
        return None
    return round(sum(closes[-window:]) / window, 4)


def rsi(closes: list[float], period: int = 14) -> float | None:
    """Wilder RSI."""
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 1)


def momentum_pct(closes: list[float], days: int) -> float | None:
    if len(closes) <= days or closes[-1 - days] == 0:
        return None
    return round((closes[-1] / closes[-1 - days] - 1) * 100, 2)


def stdev_returns_pct(closes: list[float], window: int = 20) -> float | None:
    if len(closes) < window + 1:
        return None
    rets = [closes[i] / closes[i - 1] - 1 for i in range(len(closes) - window, len(closes))]
    m = sum(rets) / len(rets)
    var = sum((r - m) ** 2 for r in rets) / len(rets)
    return round((var ** 0.5) * 100, 2)


# ─────────────────────── 스냅샷 ───────────────────────
@dataclass
class TechSnapshot:
    ticker: str
    ok: bool = False
    error: str | None = None
    price: float | None = None
    rsi14: float | None = None
    sma20: float | None = None
    sma50: float | None = None
    sma120: float | None = None
    sma200: float | None = None
    pct_vs_sma120: float | None = None
    pct_vs_sma200: float | None = None
    high_52w: float | None = None
    low_52w: float | None = None
    pct_off_high: float | None = None
    mom_1m: float | None = None
    mom_3m: float | None = None
    vol_20d: float | None = None
    trend: str = ""
    trigger_hit: bool = False
    trigger_desc: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary_line(self) -> str:
        if not self.ok:
            return f"{self.ticker}: 데이터 없음 ({self.error})"
        bits = [f"{self.ticker} {self.price:,.2f}" if self.price else self.ticker]
        if self.rsi14 is not None:
            bits.append(f"RSI {self.rsi14}")
        if self.pct_vs_sma120 is not None:
            bits.append(f"120MA {self.pct_vs_sma120:+.1f}%")
        if self.pct_off_high is not None:
            bits.append(f"52주고점 {self.pct_off_high:+.1f}%")
        if self.trend:
            bits.append(self.trend)
        if self.trigger_hit:
            bits.append(f"🎯 {self.trigger_desc}")
        return " | ".join(bits)

    def to_context(self) -> str:
        """Claude 프롬프트용 정량 요약."""
        if not self.ok:
            return f"{self.ticker}: 정량 데이터 없음({self.error}) — 기술적 판단은 unknown"
        parts = [
            f"price={self.price}", f"RSI14={self.rsi14}",
            f"SMA50={self.sma50}", f"SMA120={self.sma120}", f"SMA200={self.sma200}",
            f"vs120MA={self.pct_vs_sma120}%", f"vs200MA={self.pct_vs_sma200}%",
            f"52w_high={self.high_52w}", f"off_high={self.pct_off_high}%",
            f"mom_1m={self.mom_1m}%", f"mom_3m={self.mom_3m}%", f"vol20d={self.vol_20d}%",
            f"추세={self.trend}", f"트리거={'HIT '+self.trigger_desc if self.trigger_hit else 'no'}",
        ]
        return ", ".join(str(p) for p in parts)


def analyze_series(ticker: str, closes: list[float], *, rsi_below: float = 35,
                   ma_support_days: int = 120, tolerance: float = 0.03) -> TechSnapshot:
    """종가 리스트 → 기술적 스냅샷 + 매수 트리거 판정."""
    if not closes:
        return TechSnapshot(ticker=ticker, ok=False, error="가격 히스토리 없음")
    price = closes[-1]
    s = TechSnapshot(ticker=ticker, ok=True, price=round(price, 4))
    s.rsi14 = rsi(closes, 14)
    s.sma20 = sma(closes, 20)
    s.sma50 = sma(closes, 50)
    s.sma120 = sma(closes, ma_support_days)
    s.sma200 = sma(closes, 200)
    s.mom_1m = momentum_pct(closes, 21)
    s.mom_3m = momentum_pct(closes, 63)
    s.vol_20d = stdev_returns_pct(closes, 20)
    window = closes[-252:] if len(closes) >= 252 else closes
    s.high_52w = round(max(window), 4)
    s.low_52w = round(min(window), 4)
    if s.high_52w:
        s.pct_off_high = round((price / s.high_52w - 1) * 100, 2)
    if s.sma120:
        s.pct_vs_sma120 = round((price / s.sma120 - 1) * 100, 2)
    if s.sma200:
        s.pct_vs_sma200 = round((price / s.sma200 - 1) * 100, 2)

    # 추세
    if s.sma200 is not None:
        s.trend = "상승추세(200일선 위)" if price >= s.sma200 else "조정/하락(200일선 아래)"
    elif s.sma50 is not None:
        s.trend = "상승(50일선 위)" if price >= s.sma50 else "약세(50일선 아래)"

    # 매수 트리거: RSI 과매도 + 지지 이평선 근접(±tolerance)
    near_ma = s.sma120 is not None and abs(price / s.sma120 - 1) <= tolerance
    oversold = s.rsi14 is not None and s.rsi14 <= rsi_below
    if oversold and near_ma:
        s.trigger_hit = True
        s.trigger_desc = f"RSI {s.rsi14}≤{rsi_below:g} + {ma_support_days}일선 지지({s.pct_vs_sma120:+.1f}%)"

    # 관찰 노트
    if s.rsi14 is not None:
        if s.rsi14 <= 30:
            s.notes.append("RSI 과매도(≤30)")
        elif s.rsi14 >= 70:
            s.notes.append("RSI 과매수(≥70)")
    if s.pct_off_high is not None and s.pct_off_high <= -20:
        s.notes.append(f"52주 고점 대비 {s.pct_off_high:.0f}% (조정 구간)")
    if s.sma200 is not None and price < s.sma200:
        s.notes.append("200일선 아래")
    return s


class QuantEngine:
    """정량 도구 — 가격 히스토리를 받아 기술적 스냅샷을 만든다."""

    def __init__(self, market, rsi_below: float = 35, ma_support_days: int = 120):
        self.market = market
        self.rsi_below = rsi_below
        self.ma_support_days = ma_support_days

    def snapshot(self, ticker: str, period: str = "1y") -> TechSnapshot:
        closes = self.market.history_closes(ticker, period=period)
        if not closes:
            return TechSnapshot(ticker=ticker, ok=False,
                                error="가격 히스토리 없음(네트워크 차단 또는 티커 오류)")
        return analyze_series(ticker, closes, rsi_below=self.rsi_below,
                              ma_support_days=self.ma_support_days)

    def scan(self, tickers: list[str], period: str = "1y") -> dict[str, TechSnapshot]:
        return {t: self.snapshot(t, period) for t in tickers}
