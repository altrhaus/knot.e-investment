"""AMQS-NDX — 나스닥 4-Factor 모멘텀 퀀트 엔진.

    유니버스(나스닥 대형·성장 41종)
       → 레짐 판정(QQQ 200일선 · VIX)        : 총 투자비중 결정
       → 4-Factor 채점(모멘텀·추세·RS·리스크) : 종목 서열
       → 거시 적합성(TNX·SPX·VIX × 세그먼트) : 금리 국면 보정
       → 점프 리스크 필터(갭 발생 이력·실적일): 비중 캡/제외
       → Top-8 비중 배분                      : 나머지는 현금

설계 원칙은 knot.e 전체와 같다 — 계산은 순수 함수로 분리해 네트워크 없이 검증
가능하게 하고, 수집 실패는 조용히 None 으로 흡수한다(페이지는 죽지 않는다).
결과는 4시간 디스크 캐시(data/cache/amqs_ndx.json)에 저장한다.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .quant import sma, momentum_pct, stdev_returns_pct

ROOT = Path(__file__).resolve().parent.parent
CACHE_FILE = ROOT / "data" / "cache" / "amqs_ndx.json"
UNIVERSE_FILE = ROOT / "data" / "nasdaq-universe.json"
CACHE_TTL_SEC = 4 * 3600

BENCH = "QQQ"      # 레짐 벤치마크 (나스닥100)
BROAD = "SPY"      # 광의 시장
VIX = "^VIX"       # 변동성
TNX = "^TNX"       # 미 10년물 국채수익률

# 4-Factor 배점 (합 100). 바이오판(AMQS-BIO)은 거시 25%지만 나스닥은 10%.
FACTOR_WEIGHTS = {
    "momentum": 40,   # 12-1M 20 · 6M 12 · 1M 8
    "trend": 25,      # 200일선 이격 10 · 골든크로스 7 · 52주 고점 근접 8
    "rs": 15,         # QQQ 대비 63일 초과수익
    "risk": 10,       # 20일 변동성 6 · 120일 최대낙폭 4
    "macro": 10,      # 금리·리스크 국면 × 세그먼트 민감도
}

# 레짐 임계값
VIX_RISK_ON = 28.0        # 이 미만이면 리스크 선호
VIX_RISK_OFF = 35.0       # 이 이상이면 무조건 Risk-Off
CRASH_5D = -7.0           # QQQ 5일 수익률이 이 밑이면 레짐 한 단계 강등
EXPOSURE = {"Risk-On": 1.00, "Neutral": 0.60, "Risk-Off": 0.25}

# 포트폴리오 구성 규칙
TOP_N = 8
MIN_SCORE = 60.0          # 이 점수 미만은 편입하지 않는다(현금 증가)
MAX_PER_SEGMENT = 2       # 서브테마(세그먼트)당 최대 종목 수 — 한 테마 몰빵 방지
SCORE_TILT = 0.25         # 캡 대비 ±25% 만 점수로 기울인다(과최적화 방지)
JUMP_CAP_FACTOR = 0.5     # 점프 리스크 종목은 캡의 절반

# 포지션 캡은 임의의 숫자가 아니라 켈리 기준에서 뽑는다(풀 켈리 → 1/4 켈리).
# 나스닥 모멘텀 종목의 보수적 가정: 이기면 +45%, 지면 -30%(실적 갭 + 추세 붕괴), 승률 45%.
KELLY = {"win_rate": 0.45, "win_payoff": 0.45, "loss_gap": 0.30, "divisor": 4}
POSITION_CAP_MIN = 0.03   # 1/4 켈리가 아무리 작아도 3% 밑으로는 안 내린다
POSITION_CAP_MAX = 0.12   # 아무리 커도 종목당 12% 상한

EXIT_MOM_BELOW = 0.0      # 12-1 모멘텀이 이 아래면 EXIT(청산/편입 금지)
CORE_SCORE = 70.0         # 이 점수 이상 + 추세 조건 충족이면 CORE

# 점프 리스크 필터
JUMP_THRESHOLD = 8.0      # 일간 ±8% 이상을 '갭'으로 본다
JUMP_WINDOW = 120         # 최근 120거래일
JUMP_CAP_AT = 2           # 2회 이상 → 비중 절반 캡
JUMP_EXCLUDE_AT = 4       # 4회 이상 → 편입 제외(관찰만)


# ─────────────────────── 순수 지표 함수 ───────────────────────
def daily_returns(closes: list[float]) -> list[float]:
    return [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))
            if closes[i - 1]]


def mom_12_1(closes: list[float]) -> float | None:
    """12-1 모멘텀 — 최근 1개월을 제외한 12개월 수익률(단기 반전 제거)."""
    if len(closes) < 253 or not closes[-253]:
        return None
    return round((closes[-22] / closes[-253] - 1) * 100, 2)


def max_drawdown_pct(closes: list[float], window: int = 120) -> float | None:
    """구간 최대낙폭(음수 %)."""
    seg = closes[-window:] if len(closes) >= window else closes
    if len(seg) < 2:
        return None
    peak, mdd = seg[0], 0.0
    for c in seg:
        peak = max(peak, c)
        if peak:
            mdd = min(mdd, c / peak - 1)
    return round(mdd * 100, 2)


def jump_count(closes: list[float], window: int = JUMP_WINDOW,
               threshold: float = JUMP_THRESHOLD) -> int:
    """최근 window 거래일 중 일간 ±threshold% 이상 움직인 횟수."""
    rets = daily_returns(closes)
    seg = rets[-window:] if len(rets) >= window else rets
    return sum(1 for r in seg if abs(r) * 100 >= threshold)


def excess_return_pct(closes: list[float], bench: list[float] | None,
                      days: int = 63) -> float | None:
    """벤치마크 대비 초과수익률(%p)."""
    a = momentum_pct(closes, days)
    b = momentum_pct(bench, days) if bench else None
    if a is None or b is None:
        return None
    return round(a - b, 2)


def pct_rank(values: list[float], v: float | None) -> float:
    """횡단면 백분위(0~1). 값이 없으면 중립 0.5."""
    if v is None:
        return 0.5
    vals = [x for x in values if x is not None]
    if not vals:
        return 0.5
    below = sum(1 for x in vals if x < v)
    ties = sum(1 for x in vals if x == v)
    return round((below + 0.5 * ties) / len(vals), 4)


def clip(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# ─────────────────────── 레짐 · 거시 ───────────────────────
def judge_regime(qqq: list[float] | None, vix_level: float | None,
                 spy: list[float] | None) -> dict[str, Any]:
    """QQQ 200일선 + VIX 로 레짐과 총 투자비중을 정한다."""
    out: dict[str, Any] = {
        "regime": "Unknown", "exposure": 0.0, "price": None, "sma200": None,
        "vix": vix_level, "mom_5d": None, "bench_5d": None,
        "above_200ma": None, "reasons": [], "verdict": "",
        "downgraded": False,
    }
    if not qqq:
        out["reasons"].append("QQQ 가격 히스토리 없음 — 레짐 판정 불가")
        out["verdict"] = "데이터 없음 — 신규 편입 보류"
        return out

    price = qqq[-1]
    ma200 = sma(qqq, 200)
    out["price"] = round(price, 2)
    out["sma200"] = ma200
    out["mom_5d"] = momentum_pct(qqq, 5)
    out["bench_5d"] = momentum_pct(spy, 5) if spy else None
    above = ma200 is not None and price >= ma200
    out["above_200ma"] = above

    trend_ok = above
    vol_ok = vix_level is not None and vix_level < VIX_RISK_ON
    if vix_level is not None and vix_level >= VIX_RISK_OFF:
        regime = "Risk-Off"
    elif trend_ok and vol_ok:
        regime = "Risk-On"
    elif trend_ok or vol_ok:
        regime = "Neutral"
    else:
        regime = "Risk-Off"

    # 급락 가드 — 5일 -7% 이하이면 한 단계 강등
    if out["mom_5d"] is not None and out["mom_5d"] <= CRASH_5D and regime != "Risk-Off":
        regime = "Neutral" if regime == "Risk-On" else "Risk-Off"
        out["downgraded"] = True
        out["reasons"].append(f"QQQ 5일 {out['mom_5d']:+.1f}% — 급락 가드로 한 단계 강등")

    out["regime"] = regime
    out["exposure"] = EXPOSURE[regime]
    if ma200 is not None:
        out["reasons"].append(
            f"QQQ {price:,.2f} / 200MA {ma200:,.2f} — {'위' if above else '아래'}")
    else:
        out["reasons"].append("200일 데이터 부족 — 추세 조건 미판정")
    if vix_level is not None:
        out["reasons"].append(f"VIX {vix_level:.1f} ({'28 미만' if vol_ok else '28 이상'})")
    else:
        out["reasons"].append("VIX 데이터 없음")

    verdict = {
        "Risk-On": f"모델상 풀 배분(100%) 구간이나, 종목별 캡 때문에 실제 비중은 더 낮을 수 있습니다.",
        "Neutral": "한 조건만 충족 — 부분 배분(60%). 나머지는 현금으로 남깁니다.",
        "Risk-Off": "추세·변동성 모두 불리 — 방어 배분(25%). 신규 편입은 최소화합니다.",
    }[regime]
    out["verdict"] = verdict
    return out


def judge_macro(tnx: list[float] | None, spy: list[float] | None,
                vix_level: float | None) -> dict[str, Any]:
    """금리(TNX 60일 추세) · SPX 200일선 · VIX → 거시 국면 두 축."""
    out: dict[str, Any] = {
        "tnx": None, "tnx_60d": None, "rate_pressure": 0.0,
        "spx_above_200ma": None, "vix": vix_level, "risk_appetite": 0.0,
        "labels": {}, "notes": [],
    }
    if tnx:
        out["tnx"] = round(tnx[-1], 2)
        out["tnx_60d"] = momentum_pct(tnx, 60)
    # 금리 압력: 60일 +15% 이상 급등이면 +1(롱듀레이션 불리), -15%면 -1(유리)
    if out["tnx_60d"] is not None:
        out["rate_pressure"] = round(clip(out["tnx_60d"] / 15.0, -1.0, 1.0), 3)

    spx_above = None
    if spy:
        ma200 = sma(spy, 200)
        if ma200 is not None:
            spx_above = spy[-1] >= ma200
            out["spx_ma200"] = ma200
            out["spx_price"] = round(spy[-1], 2)
    out["spx_above_200ma"] = spx_above

    # 리스크 선호: SPX 200선 위 + VIX 20 미만 = +1, 둘 다 아니면 -1
    appetite = 0.0
    if spx_above is True:
        appetite += 0.5
    elif spx_above is False:
        appetite -= 0.5
    if vix_level is not None:
        if vix_level < 20:
            appetite += 0.5
        elif vix_level >= VIX_RISK_ON:
            appetite -= 0.5
    out["risk_appetite"] = round(appetite, 3)

    rp = out["rate_pressure"]
    out["labels"] = {
        "rate": ("금리 상승 압력" if rp > 0.25 else
                 "금리 하락(완화)" if rp < -0.25 else "금리 중립"),
        "risk": ("리스크 선호" if appetite > 0.25 else
                 "리스크 회피" if appetite < -0.25 else "중립"),
    }
    if rp > 0.25:
        out["notes"].append("10Y 60일 상승 — 롱듀레이션(소프트웨어) 감점, 방어 세그먼트 상대 가점")
    if rp < -0.25:
        out["notes"].append("10Y 60일 하락 — 롱듀레이션 가점")
    if appetite <= -0.5:
        out["notes"].append("리스크 회피 — 고베타(반도체) 감점")
    return out


def macro_fit(macro: dict[str, Any], duration: float, beta: float) -> float:
    """세그먼트 듀레이션·베타를 거시 국면에 대입 → 0~10점."""
    base = 5.0
    score = base - 3.0 * macro.get("rate_pressure", 0.0) * duration \
                 + 2.0 * macro.get("risk_appetite", 0.0) * beta
    return round(clip(score, 0.0, 10.0), 2)


# ─────────────────────── 종목 채점 ───────────────────────
@dataclass
class Raw:
    """종목별 원시 지표 — 횡단면 랭킹 전 단계."""
    ticker: str
    name: str
    segment: str
    ok: bool = False
    error: str | None = None
    price: float | None = None
    m12_1: float | None = None
    m6: float | None = None
    m1: float | None = None
    vs_sma200: float | None = None
    golden_cross: bool = False
    off_high: float | None = None
    rs63: float | None = None
    vol20: float | None = None
    mdd120: float | None = None
    jumps: int = 0


def measure(ticker: str, name: str, segment: str, closes: list[float] | None,
            bench: list[float] | None) -> Raw:
    """가격 히스토리 → 원시 지표."""
    r = Raw(ticker=ticker, name=name, segment=segment)
    if not closes or len(closes) < 60:
        r.error = "가격 히스토리 부족(최소 60거래일)"
        return r
    r.ok = True
    price = closes[-1]
    r.price = round(price, 2)
    r.m12_1 = mom_12_1(closes)
    r.m6 = momentum_pct(closes, 126)
    r.m1 = momentum_pct(closes, 21)
    ma50, ma200 = sma(closes, 50), sma(closes, 200)
    if ma200:
        r.vs_sma200 = round((price / ma200 - 1) * 100, 2)
    r.golden_cross = bool(ma50 and ma200 and ma50 > ma200)
    window = closes[-252:] if len(closes) >= 252 else closes
    high = max(window)
    if high:
        r.off_high = round((price / high - 1) * 100, 2)
    r.rs63 = excess_return_pct(closes, bench, 63)
    r.vol20 = stdev_returns_pct(closes, 20)
    r.mdd120 = max_drawdown_pct(closes, 120)
    r.jumps = jump_count(closes)
    return r


def score_universe(raws: list[Raw], macro: dict[str, Any],
                   segments: dict[str, dict],
                   archetype_of: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """횡단면 백분위로 4-Factor 를 채점하고 점프 리스크 플래그를 붙인다."""
    live = [r for r in raws if r.ok]
    cols = {
        "m12_1": [r.m12_1 for r in live],
        "m6": [r.m6 for r in live],
        "m1": [r.m1 for r in live],
        "vs_sma200": [r.vs_sma200 for r in live],
        "off_high": [r.off_high for r in live],
        "rs63": [r.rs63 for r in live],
        "vol20": [-r.vol20 if r.vol20 is not None else None for r in live],
        "mdd120": [r.mdd120 for r in live],  # 덜 깊을수록(0에 가까울수록) 높음
    }

    rows: list[dict[str, Any]] = []
    for r in raws:
        seg = segments.get(r.segment, {"duration": 1.0, "beta": 1.0})
        row: dict[str, Any] = {
            "ticker": r.ticker, "name": r.name, "segment": r.segment,
            "archetype": (archetype_of or {}).get(r.ticker, ""),
            "ok": r.ok, "error": r.error, "price": r.price,
            "m12_1": r.m12_1, "m6": r.m6, "m1": r.m1,
            "vs_sma200": r.vs_sma200, "golden_cross": r.golden_cross,
            "off_high": r.off_high, "rs63": r.rs63, "vol20": r.vol20,
            "mdd120": r.mdd120, "jumps": r.jumps,
        }
        if not r.ok:
            row.update({"momentum": 0, "trend": 0, "rs": 0, "risk": 0,
                        "macro": 0, "total": 0.0, "jump_risk": "—",
                        "excluded": True, "capped": False,
                        "signal": "—", "flags": ["데이터 없음"]})
            rows.append(row)
            continue

        momentum = (20 * pct_rank(cols["m12_1"], r.m12_1)
                    + 12 * pct_rank(cols["m6"], r.m6)
                    + 8 * pct_rank(cols["m1"], r.m1))
        trend = (10 * pct_rank(cols["vs_sma200"], r.vs_sma200)
                 + (7.0 if r.golden_cross else 0.0)
                 + 8 * pct_rank(cols["off_high"], r.off_high))
        rs = 15 * pct_rank(cols["rs63"], r.rs63)
        risk = (6 * pct_rank(cols["vol20"], -r.vol20 if r.vol20 is not None else None)
                + 4 * pct_rank(cols["mdd120"], r.mdd120))
        mac = macro_fit(macro, seg.get("duration", 1.0), seg.get("beta", 1.0))

        flags: list[str] = []
        capped = r.jumps >= JUMP_CAP_AT
        excluded = r.jumps >= JUMP_EXCLUDE_AT
        if excluded:
            flags.append(f"갭 {r.jumps}회 — 편입 제외")
        elif capped:
            flags.append(f"갭 {r.jumps}회 — 비중 캡의 {JUMP_CAP_FACTOR:.0%}")
        if r.vs_sma200 is not None and r.vs_sma200 < 0:
            flags.append("200일선 아래")

        row.update({
            "momentum": round(momentum, 1), "trend": round(trend, 1),
            "rs": round(rs, 1), "risk": round(risk, 1), "macro": round(mac, 1),
            "total": round(momentum + trend + rs + risk + mac, 1),
            "jump_risk": ("높음" if r.jumps >= JUMP_EXCLUDE_AT else
                          "중간" if r.jumps >= JUMP_CAP_AT else "낮음"),
            "excluded": excluded, "capped": capped, "flags": flags,
        })
        rows.append(row)

    rows.sort(key=lambda x: x["total"], reverse=True)
    for i, row in enumerate(rows, 1):
        row["rank"] = i
        if "signal" not in row:
            row["signal"] = classify_signal(row)
            if row["signal"] == "EXIT" and not row["excluded"]:
                row["flags"].insert(0, "EXIT — 모멘텀/추세 이탈")
    return rows


# ─────────────────────── 포지션 사이징(켈리) · 신호 ───────────────────────
def kelly_fraction(win_rate: float, win_payoff: float, loss_gap: float) -> float:
    """풀 켈리 f* = (p·b − q·l) / (b·l). 기대값이 음수면 0."""
    if win_payoff <= 0 or loss_gap <= 0:
        return 0.0
    p, q = win_rate, 1.0 - win_rate
    f = (p * win_payoff - q * loss_gap) / (win_payoff * loss_gap)
    return round(max(f, 0.0), 4)


def sizing(kelly: dict[str, Any] | None = None) -> dict[str, Any]:
    """켈리 가정 → 종목당 포지션 캡."""
    k = {**KELLY, **(kelly or {})}
    full = kelly_fraction(k["win_rate"], k["win_payoff"], k["loss_gap"])
    fractional = full / max(k["divisor"], 1)
    cap = round(clip(fractional, POSITION_CAP_MIN, POSITION_CAP_MAX), 4)
    return {
        **k,
        "full_kelly": full,
        "fractional_kelly": round(fractional, 4),
        "position_cap": cap,
        "clipped": abs(cap - fractional) > 1e-4,
        "max_gross": round(cap * TOP_N, 4),
    }


def classify_signal(row: dict[str, Any]) -> str:
    """CORE / SATELLITE / EXIT / WATCH — 편입 여부와 성격을 한 단어로."""
    if not row["ok"]:
        return "—"
    if row["excluded"]:
        return "EXIT"
    if row["m12_1"] is not None and row["m12_1"] < EXIT_MOM_BELOW:
        return "EXIT"
    if row["vs_sma200"] is not None and row["vs_sma200"] < 0:
        return "EXIT"
    if row["total"] < MIN_SCORE:
        return "WATCH"
    if row["total"] >= CORE_SCORE and row["golden_cross"] and not row["capped"]:
        return "CORE"
    return "SATELLITE"


# ─────────────────────── 비중 배분 ───────────────────────
def build_weights(rows: list[dict[str, Any]], exposure: float,
                  cap: float) -> tuple[list[dict], float, list[str]]:
    """켈리 캡을 기준선으로 상위 종목에 비중을 준다 — 점수는 ±25%만 기울인다.

    비중 = 캡 × (1 + 0.25 × 점수기울기) × 레짐 투자비중.
    서브테마당 2종목까지만 뽑고, 점프 리스크 종목은 캡의 절반. 남는 몫은 현금.
    """
    notes: list[str] = []
    eligible = [r for r in rows if r["signal"] in ("CORE", "SATELLITE")]
    if not eligible:
        notes.append(f"편입 기준({MIN_SCORE:.0f}점 · 12-1 모멘텀 양수 · 200일선 위) 통과 종목 없음 — 전액 현금")
        return [], 1.0, notes

    picks: list[dict] = []
    per_seg: dict[str, int] = {}
    skipped: list[str] = []
    for r in eligible:  # rows 는 이미 총점 내림차순
        seg = r["segment"]
        if per_seg.get(seg, 0) >= MAX_PER_SEGMENT:
            skipped.append(r["ticker"])
            continue
        per_seg[seg] = per_seg.get(seg, 0) + 1
        picks.append(r)
        if len(picks) == TOP_N:
            break
    if skipped:
        notes.append(f"서브테마당 {MAX_PER_SEGMENT}종목 제한으로 제외: {', '.join(skipped[:6])}"
                     + (" 외" if len(skipped) > 6 else ""))
    if len(picks) < TOP_N:
        notes.append(f"기준 통과 {len(picks)}종목 — Top-{TOP_N} 미달분은 현금으로 남깁니다")

    scores = [r["total"] for r in picks]
    lo, hi = min(scores), max(scores)
    out = []
    for r in picks:
        z = 0.0 if hi - lo < 1e-9 else ((r["total"] - lo) / (hi - lo)) * 2 - 1  # -1~+1
        base = cap * (1 + SCORE_TILT * z)
        if r["capped"]:
            base *= JUMP_CAP_FACTOR
        out.append({**r, "weight": round(base * exposure, 4),
                    "weight_pre_regime": round(base, 4), "tilt": round(z, 3)})
    out.sort(key=lambda x: x["weight"], reverse=True)
    for i, x in enumerate(out, 1):
        x["pos"] = i          # 포트폴리오 순위(유니버스 순위 rank 와 별개)
    gross = sum(x["weight"] for x in out)
    return out, round(max(1.0 - gross, 0.0), 4), notes


def falsification(rows: list[dict[str, Any]], regime: dict, macro: dict) -> dict[str, Any]:
    """전략 전제가 깨졌는지 보는 반증 조건 — 둘 이상 충족이면 배분을 절반으로."""
    live = [r for r in rows if r["ok"]]
    above = [r for r in live if r["vs_sma200"] is not None and r["vs_sma200"] > 0]
    breadth = round(len(above) / len(live), 3) if live else None
    moms = [r["m12_1"] for r in live if r["m12_1"] is not None]
    avg_mom = round(sum(moms) / len(moms), 2) if moms else None
    vix = regime.get("vix")

    checks = [
        {"cond": "QQQ가 200일선 아래로 이탈", "hit": regime.get("above_200ma") is False,
         "detail": f"QQQ {num_or(regime.get('price'))} / 200MA {num_or(regime.get('sma200'))}",
         "impact": "레짐 강등 — 총 투자비중 축소"},
        {"cond": "유니버스 200일선 상회 비율 < 40%", "hit": breadth is not None and breadth < 0.40,
         "detail": f"현재 {breadth:.0%}" if breadth is not None else "데이터 없음",
         "impact": "모멘텀 폭(breadth) 붕괴 — 신규 편입 중단"},
        {"cond": "유니버스 평균 12-1 모멘텀 < 0", "hit": avg_mom is not None and avg_mom < 0,
         "detail": f"현재 {avg_mom:+.1f}%" if avg_mom is not None else "데이터 없음",
         "impact": "추세 추종 전제 훼손 — 전략 중단 검토"},
        {"cond": "10Y 60일 +15% 이상 급등", "hit": macro.get("rate_pressure", 0) >= 1.0,
         "detail": f"TNX 60일 {num_or(macro.get('tnx_60d'), '%')}",
         "impact": "롱듀레이션(소프트웨어·AI-네이티브) 비중 축소"},
        {"cond": f"VIX {VIX_RISK_ON:.0f} 이상", "hit": vix is not None and vix >= VIX_RISK_ON,
         "detail": f"현재 {vix}" if vix is not None else "데이터 없음",
         "impact": "Risk-Off — 방어 배분(25%)"},
    ]
    hits = sum(1 for c in checks if c["hit"])
    return {"checks": checks, "hits": hits, "breadth": breadth, "avg_mom": avg_mom,
            "halve": hits >= 2}


def num_or(v: Any, suffix: str = "", dash: str = "—") -> str:
    return dash if v is None else f"{v:,.2f}{suffix}"


# ─────────────────────── 엔진 ───────────────────────
class AmqsNdx:
    """나스닥 AMQS 스냅샷 빌더. fetch 는 ticker → 종가 리스트 콜러블."""

    def __init__(self, fetch: Callable[[str], list[float] | None] | None = None,
                 universe_file: Path | None = None, demo: bool = False,
                 cache_file: Path | None = None,
                 fetch_many: Callable[[list[str]], dict[str, list[float] | None]] | None = None):
        self.universe_file = universe_file or UNIVERSE_FILE
        self.cache_file = cache_file or CACHE_FILE
        self.demo = demo
        self._fetch = fetch or (demo_series if demo else _yf_fetch)
        # 배치 조회가 있으면 40여 종목을 한 번에 받는다(대시보드 응답 시간).
        self._fetch_many = fetch_many or (None if (demo or fetch) else _yf_fetch_many)

    # --- 유니버스 ---
    def load_universe(self) -> dict[str, Any]:
        return json.loads(self.universe_file.read_text(encoding="utf-8"))

    # --- 캐시 ---
    def cached(self, ttl: int = CACHE_TTL_SEC) -> dict[str, Any] | None:
        try:
            data = json.loads(self.cache_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if time.time() - data.get("generated_ts", 0) > ttl:
            return None
        if bool(data.get("demo")) != bool(self.demo):
            return None
        data["from_cache"] = True
        return data

    def save_cache(self, snap: dict[str, Any]) -> None:
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(json.dumps(snap, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
        except OSError:
            pass

    # --- 스냅샷 ---
    def snapshot(self, refresh: bool = False, ttl: int = CACHE_TTL_SEC) -> dict[str, Any]:
        if not refresh:
            hit = self.cached(ttl)
            if hit:
                return hit
        snap = self.build()
        self.save_cache(snap)
        return snap

    def build(self) -> dict[str, Any]:
        uni = self.load_universe()
        segments = uni.get("segments", {})
        entries = uni.get("universe", [])
        warnings: list[str] = []

        tickers = [BENCH, BROAD, VIX, TNX] + [e["ticker"] for e in entries]
        if self._fetch_many:
            series = self._fetch_many(tickers)
        else:
            series = {t: self._fetch(t) for t in tickers}

        qqq, spy = series.get(BENCH), series.get(BROAD)
        vix_series, tnx_series = series.get(VIX), series.get(TNX)
        vix_level = round(vix_series[-1], 2) if vix_series else None

        regime = judge_regime(qqq, vix_level, spy)
        macro = judge_macro(tnx_series, spy, vix_level)

        raws = [measure(e["ticker"], e.get("name", e["ticker"]), e.get("segment", "기타"),
                        series.get(e["ticker"]), qqq) for e in entries]
        missing = [r.ticker for r in raws if not r.ok]
        if missing:
            warnings.append(f"가격 수집 실패 {len(missing)}종목: {', '.join(missing[:8])}"
                            + (" 외" if len(missing) > 8 else ""))
        if not qqq:
            warnings.append("QQQ 히스토리를 못 받아 레짐·상대강도 판정이 비어 있습니다")

        arch_of = {e["ticker"]: e.get("archetype", "") for e in entries}
        rows = score_universe(raws, macro, segments, arch_of)
        size = sizing(uni.get("kelly"))
        top, cash, notes = build_weights(rows, regime["exposure"], size["position_cap"])
        falsify = falsification(rows, regime, macro)
        if falsify["halve"]:
            notes.append("반증 조건 2개 이상 충족 — 테마 배분을 절반으로 줄이는 구간입니다")

        # 아키타입별 배분 요약 (A 내재화 / B 외주 / C 인프라 / D AI-네이티브)
        arch_alloc: dict[str, float] = {}
        for x in top:
            key = x.get("archetype") or "—"
            arch_alloc[key] = round(arch_alloc.get(key, 0.0) + x["weight"], 4)

        now = datetime.now()
        return {
            "strategy": "AMQS-NDX",
            "generated_at": now.strftime("%Y. %m. %d. %H:%M:%S"),
            "generated_ts": time.time(),
            "demo": self.demo,
            "from_cache": False,
            "cache_ttl_hours": CACHE_TTL_SEC // 3600,
            "universe_count": len(entries),
            "scored_count": sum(1 for r in rows if r["ok"]),
            "benchmark": BENCH,
            "regime": regime,
            "macro": macro,
            "segments": segments,
            "archetypes": uni.get("archetypes", {}),
            "archetype_alloc": arch_alloc,
            "factor_weights": FACTOR_WEIGHTS,
            "sizing": size,
            "falsification": falsify,
            "rules": {
                "vix_risk_on": VIX_RISK_ON, "vix_risk_off": VIX_RISK_OFF,
                "crash_5d": CRASH_5D, "exposure": EXPOSURE, "top_n": TOP_N,
                "min_score": MIN_SCORE, "core_score": CORE_SCORE,
                "position_cap": size["position_cap"], "score_tilt": SCORE_TILT,
                "jump_cap_factor": JUMP_CAP_FACTOR, "max_per_segment": MAX_PER_SEGMENT,
                "jump_threshold": JUMP_THRESHOLD, "jump_window": JUMP_WINDOW,
                "jump_cap_at": JUMP_CAP_AT, "jump_exclude_at": JUMP_EXCLUDE_AT,
                "exit_mom_below": EXIT_MOM_BELOW,
            },
            "rows": rows,
            "top": top,
            "gross_pct": round(1.0 - cash, 4),
            "cash_pct": cash,
            "exits": [r["ticker"] for r in rows if r.get("signal") == "EXIT"][:12],
            "notes": notes,
            "warnings": warnings,
        }


# ─────────────────────── 데이터 소스 ───────────────────────
def _yf_fetch(ticker: str) -> list[float] | None:
    """yfinance 종가 2년치. 실패는 None(페이지는 계속 그려진다)."""
    from .market_data import MarketData
    return MarketData().history_closes(ticker, period="2y")


def _yf_fetch_many(tickers: list[str]) -> dict[str, list[float] | None]:
    """유니버스 전체를 한 번에 — 개별 조회보다 훨씬 빠르다."""
    from .market_data import MarketData
    return MarketData().history_closes_batch(tickers, period="2y")


def demo_series(ticker: str, n: int = 520) -> list[float]:
    """네트워크 없이 레이아웃을 확인하기 위한 결정적 합성 시계열(데모 전용)."""
    seed = int(hashlib.sha256(ticker.encode()).hexdigest()[:8], 16)
    base = {"^VIX": 15.0, "^TNX": 4.2, "QQQ": 520.0, "SPY": 610.0}.get(ticker, 60.0 + seed % 340)
    drift = ((seed >> 3) % 21 - 7) / 10000.0
    vol = 0.008 + ((seed >> 7) % 18) / 1000.0
    if ticker in ("^VIX", "^TNX"):
        drift, vol = 0.0, 0.02
    x, out = base, []
    state = seed
    for i in range(n):
        state = (1103515245 * state + 12345) % (2 ** 31)
        u = state / (2 ** 31) - 0.5
        shock = 0.0
        if state % 900 < 3:  # 드물게 실적 갭
            shock = (0.09 if state % 2 else -0.09)
        x = max(x * (1 + drift + vol * u * 2 + shock), 1.0)
        out.append(round(x, 4))
    return out
