"""시세/재무 데이터 도구 (기본: yfinance, 키 불필요).

네트워크가 막힌 환경에서도 앱이 죽지 않도록 모든 실패는 조용히 None 으로 처리한다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from typing import Any

# yfinance 는 조회 실패 시 자체 로그를 시끄럽게 출력한다. 우리는 Quote.error 로
# 결과를 표현하므로 라이브러리 로깅은 억제한다(네트워크 차단 환경에서도 깔끔).
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("peewee").setLevel(logging.CRITICAL)


@dataclass
class Quote:
    ticker: str
    price: float | None = None
    prev_close: float | None = None
    change_pct: float | None = None
    currency: str | None = None
    ok: bool = False
    error: str | None = None
    # W12 재무 지표 (가능한 경우)
    revenue_growth: float | None = None      # F3
    free_cashflow: float | None = None       # F4
    price_to_sales: float | None = None      # F5
    market_cap: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MarketData:
    """주가/재무 조회 도구. 오케스트레이터가 '정량 데이터'가 필요할 때 호출한다."""

    def __init__(self, provider: str = "yfinance"):
        self.provider = provider

    def quote(self, ticker: str, with_fundamentals: bool = False) -> Quote:
        if self.provider == "yfinance":
            return self._yf_quote(ticker, with_fundamentals)
        return Quote(ticker=ticker, ok=False, error=f"미지원 provider: {self.provider}")

    def quotes(self, tickers: list[str], with_fundamentals: bool = False) -> dict[str, Quote]:
        return {t: self.quote(t, with_fundamentals) for t in tickers}

    def history_closes(self, ticker: str, period: str = "1y") -> list[float] | None:
        """종가 시계열(list[float]). 정량 엔진의 입력. 실패 시 None."""
        if self.provider != "yfinance":
            return None
        try:
            import yfinance as yf
        except ImportError:
            return None
        try:
            hist = yf.Ticker(ticker).history(period=period, auto_adjust=True)
            if hist is None or hist.empty or "Close" not in hist:
                return None
            closes = [float(x) for x in hist["Close"].tolist() if x == x]  # NaN 제거
            return closes or None
        except Exception:
            return None

    def history_closes_batch(self, tickers: list[str], period: str = "1y") -> dict[str, list[float] | None]:
        """여러 티커의 종가를 한 번에 받는다(대시보드용). 실패분은 개별 조회로 보완."""
        out: dict[str, list[float] | None] = {t: None for t in tickers}
        if self.provider != "yfinance" or not tickers:
            return out
        df = None
        try:
            import yfinance as yf
            df = yf.download(tickers=" ".join(tickers), period=period, auto_adjust=True,
                             progress=False, group_by="ticker", threads=True)
        except Exception:
            df = None
        if df is not None and not getattr(df, "empty", True):
            multi = hasattr(df.columns, "levels")
            for t in tickers:
                try:
                    if multi:
                        if t not in df.columns.levels[0]:
                            continue
                        series = df[t]["Close"]
                    elif len(tickers) == 1 and "Close" in df:
                        series = df["Close"]
                    else:
                        continue
                    closes = [float(x) for x in series.tolist() if x == x]  # NaN 제거
                    out[t] = closes or None
                except Exception:
                    continue
        for t in tickers:  # 배치에서 빠진 티커만 개별 재시도
            if out[t] is None:
                out[t] = self.history_closes(t, period=period)
        return out

    # --- yfinance 구현 ---
    def _yf_quote(self, ticker: str, with_fundamentals: bool) -> Quote:
        try:
            import yfinance as yf
        except ImportError:
            return Quote(ticker=ticker, ok=False, error="yfinance 미설치 (pip install yfinance)")
        try:
            t = yf.Ticker(ticker)
            fast = getattr(t, "fast_info", {}) or {}
            price = _num(fast.get("last_price") or fast.get("lastPrice"))
            prev = _num(fast.get("previous_close") or fast.get("previousClose"))
            currency = fast.get("currency")
            q = Quote(ticker=ticker, price=price, prev_close=prev, currency=currency)
            if price is not None and prev:
                q.change_pct = round((price - prev) / prev * 100, 2)
            q.market_cap = _num(fast.get("market_cap") or fast.get("marketCap"))

            if with_fundamentals:
                info = _safe_info(t)
                q.revenue_growth = _num(info.get("revenueGrowth"))
                q.free_cashflow = _num(info.get("freeCashflow"))
                q.price_to_sales = _num(info.get("priceToSalesTrailing12Months"))
                if q.market_cap is None:
                    q.market_cap = _num(info.get("marketCap"))
                if q.price is None:
                    q.price = _num(info.get("currentPrice") or info.get("regularMarketPrice"))

            q.ok = q.price is not None
            if not q.ok and q.error is None:
                q.error = "시세 없음 (네트워크 차단 또는 잘못된 티커)"
            return q
        except Exception as e:  # 네트워크/파싱 실패 등 전부 흡수
            return Quote(ticker=ticker, ok=False, error=f"{type(e).__name__}: {e}")


def _safe_info(t) -> dict:
    try:
        return t.info or {}
    except Exception:
        return {}


def _num(v) -> float | None:
    try:
        if v is None:
            return None
        f = float(v)
        return f
    except (TypeError, ValueError):
        return None
