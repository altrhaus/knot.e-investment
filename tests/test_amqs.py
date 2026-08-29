"""AMQS-NDX 엔진 테스트 — 네트워크 없이 순수 함수와 조립 로직을 검증한다.

    python -m unittest discover tests
"""
from __future__ import annotations

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from knot import amqs


def ramp(n: int, start: float = 100.0, step: float = 0.5) -> list[float]:
    return [start + step * i for i in range(n)]


class TestIndicators(unittest.TestCase):
    def test_mom_12_1_excludes_last_month(self):
        closes = ramp(300)
        # 12-1 은 -253 → -22 구간 수익률
        expected = round((closes[-22] / closes[-253] - 1) * 100, 2)
        self.assertEqual(amqs.mom_12_1(closes), expected)

    def test_mom_12_1_needs_a_year(self):
        self.assertIsNone(amqs.mom_12_1(ramp(200)))

    def test_max_drawdown(self):
        closes = [100, 120, 60, 90]
        self.assertEqual(amqs.max_drawdown_pct(closes, window=10), -50.0)

    def test_max_drawdown_monotonic_rise_is_zero(self):
        self.assertEqual(amqs.max_drawdown_pct(ramp(150), window=120), 0.0)

    def test_jump_count(self):
        closes = [100, 100, 112, 112, 100.0, 100]  # +12%, -10.7%
        self.assertEqual(amqs.jump_count(closes, window=10, threshold=8.0), 2)
        self.assertEqual(amqs.jump_count(closes, window=10, threshold=15.0), 0)

    def test_excess_return(self):
        stock = ramp(100, 100.0, 1.0)     # 강한 상승
        bench = ramp(100, 100.0, 0.1)     # 완만한 상승
        self.assertGreater(amqs.excess_return_pct(stock, bench, 63), 0)

    def test_pct_rank_bounds_and_neutral(self):
        vals = [1.0, 2.0, 3.0, 4.0]
        self.assertEqual(amqs.pct_rank(vals, 0.0), 0.0)
        self.assertEqual(amqs.pct_rank(vals, 5.0), 1.0)
        self.assertEqual(amqs.pct_rank(vals, None), 0.5)   # 결측은 중립
        self.assertEqual(amqs.pct_rank([], 3.0), 0.5)


class TestRegime(unittest.TestCase):
    def test_risk_on(self):
        r = amqs.judge_regime(ramp(300), 14.0, ramp(300))
        self.assertEqual(r["regime"], "Risk-On")
        self.assertEqual(r["exposure"], 1.0)

    def test_neutral_when_only_vix_ok(self):
        falling = ramp(300)[::-1]                      # 200일선 아래
        r = amqs.judge_regime(falling, 14.0, ramp(300))
        self.assertEqual(r["regime"], "Neutral")

    def test_risk_off_on_extreme_vix(self):
        r = amqs.judge_regime(ramp(300), 40.0, ramp(300))
        self.assertEqual(r["regime"], "Risk-Off")
        self.assertEqual(r["exposure"], amqs.EXPOSURE["Risk-Off"])

    def test_crash_guard_downgrades(self):
        closes = ramp(300)
        closes = closes + [closes[-1] * 0.90]          # 하루 -10% → 5일 수익률 급락
        r = amqs.judge_regime(closes, 14.0, ramp(300))
        self.assertTrue(r["downgraded"])
        self.assertEqual(r["regime"], "Neutral")

    def test_no_data_is_unknown_not_crash(self):
        r = amqs.judge_regime(None, None, None)
        self.assertEqual(r["regime"], "Unknown")
        self.assertEqual(r["exposure"], 0.0)


class TestMacro(unittest.TestCase):
    def test_rate_pressure_clipped(self):
        rising = [1.0 * (1.02 ** i) for i in range(120)]   # 60일 +200%
        m = amqs.judge_macro(rising, ramp(300), 14.0)
        self.assertEqual(m["rate_pressure"], 1.0)

    def test_macro_fit_penalises_long_duration_when_rates_rise(self):
        m = {"rate_pressure": 1.0, "risk_appetite": 0.0}
        soft = amqs.macro_fit(m, duration=1.3, beta=1.1)   # 소프트웨어
        defensive = amqs.macro_fit(m, duration=0.4, beta=0.65)
        self.assertLess(soft, defensive)

    def test_macro_fit_bounds(self):
        m = {"rate_pressure": -1.0, "risk_appetite": 1.0}
        self.assertLessEqual(amqs.macro_fit(m, 2.0, 2.0), 10.0)
        m2 = {"rate_pressure": 1.0, "risk_appetite": -1.0}
        self.assertGreaterEqual(amqs.macro_fit(m2, 2.0, 2.0), 0.0)


CAP = amqs.sizing()["position_cap"]


def _row(ticker, total, segment="AI 인프라/반도체", capped=False, excluded=False,
         m12_1=25.0, vs_sma200=8.0, golden=True):
    row = {"ticker": ticker, "name": ticker, "segment": segment, "ok": True,
           "archetype": "C", "total": total, "capped": capped, "excluded": excluded,
           "m12_1": m12_1, "vs_sma200": vs_sma200, "golden_cross": golden,
           "rank": 0, "flags": []}
    row["signal"] = amqs.classify_signal(row)
    return row


class TestSizing(unittest.TestCase):
    def test_kelly_formula(self):
        # p=0.45, b=0.45, l=0.30 → (0.2025-0.165)/0.135 = 0.2778
        self.assertAlmostEqual(amqs.kelly_fraction(0.45, 0.45, 0.30), 0.2778, places=3)

    def test_negative_edge_is_zero(self):
        self.assertEqual(amqs.kelly_fraction(0.20, 0.30, 0.50), 0.0)

    def test_quarter_kelly_and_bounds(self):
        z = amqs.sizing()
        self.assertAlmostEqual(z["fractional_kelly"], z["full_kelly"] / 4, places=4)
        self.assertGreaterEqual(z["position_cap"], amqs.POSITION_CAP_MIN)
        self.assertLessEqual(z["position_cap"], amqs.POSITION_CAP_MAX)
        self.assertAlmostEqual(z["max_gross"], z["position_cap"] * amqs.TOP_N, places=4)

    def test_cap_is_clipped_when_kelly_is_huge(self):
        z = amqs.sizing({"win_rate": 0.9, "win_payoff": 2.0, "loss_gap": 0.1})
        self.assertEqual(z["position_cap"], amqs.POSITION_CAP_MAX)
        self.assertTrue(z["clipped"])


class TestSignals(unittest.TestCase):
    def test_exit_on_negative_momentum(self):
        self.assertEqual(amqs.classify_signal(_row("X", 90, m12_1=-5.0)), "EXIT")

    def test_exit_below_200ma(self):
        self.assertEqual(amqs.classify_signal(_row("X", 90, vs_sma200=-3.0)), "EXIT")

    def test_exit_when_jump_excluded(self):
        self.assertEqual(amqs.classify_signal(_row("X", 95, excluded=True)), "EXIT")

    def test_core_needs_score_and_golden_cross(self):
        self.assertEqual(amqs.classify_signal(_row("X", 75)), "CORE")
        self.assertEqual(amqs.classify_signal(_row("X", 75, golden=False)), "SATELLITE")
        self.assertEqual(amqs.classify_signal(_row("X", 75, capped=True)), "SATELLITE")

    def test_watch_below_min_score(self):
        self.assertEqual(amqs.classify_signal(_row("X", amqs.MIN_SCORE - 1)), "WATCH")


class TestWeights(unittest.TestCase):
    def test_caps_and_cash_add_up(self):
        rows = [_row(f"T{i}", 95 - i, segment=f"S{i}") for i in range(10)]
        top, cash, _ = amqs.build_weights(rows, exposure=1.0, cap=CAP)
        self.assertEqual(len(top), amqs.TOP_N)
        # 켈리 캡 ±25% 기울기를 넘지 않는다
        self.assertLessEqual(max(x["weight"] for x in top), CAP * (1 + amqs.SCORE_TILT) + 1e-4)
        self.assertAlmostEqual(sum(x["weight"] for x in top) + cash, 1.0, places=3)

    def test_score_tilt_favours_the_leader(self):
        rows = [_row(f"T{i}", 95 - i * 4, segment=f"S{i}") for i in range(8)]
        top, _, _ = amqs.build_weights(rows, exposure=1.0, cap=CAP)
        self.assertGreater(top[0]["weight"], top[-1]["weight"])
        self.assertEqual(top[0]["ticker"], "T0")

    def test_flagged_name_gets_half_cap(self):
        rows = [_row(f"T{i}", 95 - i, segment=f"S{i}") for i in range(10)]
        rows[0]["capped"] = True
        rows[0]["signal"] = amqs.classify_signal(rows[0])
        top, _, _ = amqs.build_weights(rows, exposure=1.0, cap=CAP)
        flagged = next(x for x in top if x["ticker"] == "T0")
        self.assertLessEqual(flagged["weight"], CAP * amqs.JUMP_CAP_FACTOR * 1.3)

    def test_two_names_per_segment_max(self):
        rows = [_row(f"T{i}", 95 - i, segment="AI 인프라/반도체") for i in range(10)]
        top, cash, notes = amqs.build_weights(rows, exposure=1.0, cap=CAP)
        self.assertEqual(len(top), amqs.MAX_PER_SEGMENT)
        self.assertGreater(cash, 0.8)
        self.assertTrue(any("서브테마" in n for n in notes))

    def test_regime_scales_everything(self):
        rows = [_row(f"T{i}", 95 - i, segment=f"S{i}") for i in range(10)]
        full, _, _ = amqs.build_weights(rows, exposure=1.0, cap=CAP)
        defensive, cash, _ = amqs.build_weights(rows, exposure=0.25, cap=CAP)
        self.assertAlmostEqual(sum(x["weight"] for x in defensive),
                               sum(x["weight"] for x in full) * 0.25, places=3)
        self.assertGreater(cash, 0.8)

    def test_low_scores_go_all_cash(self):
        rows = [_row(f"T{i}", amqs.MIN_SCORE - 5, segment=f"S{i}") for i in range(10)]
        top, cash, _ = amqs.build_weights(rows, exposure=1.0, cap=CAP)
        self.assertEqual(top, [])
        self.assertEqual(cash, 1.0)

    def test_exit_names_never_enter(self):
        rows = [_row("BAD", 99, m12_1=-1.0)] + \
               [_row(f"T{i}", 90 - i, segment=f"S{i}") for i in range(8)]
        top, _, _ = amqs.build_weights(rows, exposure=1.0, cap=CAP)
        self.assertNotIn("BAD", [x["ticker"] for x in top])


class TestFalsification(unittest.TestCase):
    def _rows(self, vs200, mom):
        return [{"ok": True, "vs_sma200": vs200, "m12_1": mom} for _ in range(10)]

    def test_no_hits_in_healthy_market(self):
        f = amqs.falsification(self._rows(10.0, 30.0),
                               {"above_200ma": True, "vix": 14.0, "price": 500, "sma200": 450},
                               {"rate_pressure": 0.0})
        self.assertEqual(f["hits"], 0)
        self.assertFalse(f["halve"])
        self.assertEqual(f["breadth"], 1.0)

    def test_broken_market_triggers_halving(self):
        f = amqs.falsification(self._rows(-10.0, -20.0),
                               {"above_200ma": False, "vix": 35.0, "price": 400, "sma200": 450},
                               {"rate_pressure": 1.0})
        self.assertGreaterEqual(f["hits"], 2)
        self.assertTrue(f["halve"])


class TestSnapshot(unittest.TestCase):
    """demo 데이터로 전체 파이프라인 + 페이지 렌더까지 한 번 통과시킨다."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp()) / "cache.json"
        self.engine = amqs.AmqsNdx(demo=True, cache_file=self.tmp)

    def test_build_and_render(self):
        from knot.amqs_page import render_page
        snap = self.engine.build()
        self.assertEqual(snap["scored_count"], snap["universe_count"])
        self.assertLessEqual(len(snap["top"]), amqs.TOP_N)
        self.assertAlmostEqual(snap["gross_pct"] + snap["cash_pct"], 1.0, places=3)
        self.assertIn("position_cap", snap["sizing"])
        self.assertIn("checks", snap["falsification"])
        for x in snap["top"]:
            self.assertIn(x["signal"], ("CORE", "SATELLITE"))
            self.assertIn(x["archetype"], ("A", "B", "C", "D"))
        self.assertAlmostEqual(sum(x["weight"] for x in snap["top"]) + snap["cash_pct"],
                               1.0, places=2)
        for r in snap["rows"]:
            self.assertLessEqual(r["total"], 100.0)
            self.assertGreaterEqual(r["total"], 0.0)
        page = render_page(snap, live=True)
        for chunk in ("AMQS-NDX", "점프 리스크 필터", "포지션 사이징", "반증 조건", "아키타입"):
            self.assertIn(chunk, page)

    def test_cache_roundtrip(self):
        first = self.engine.snapshot(refresh=True)
        second = self.engine.snapshot()
        self.assertTrue(second["from_cache"])
        self.assertEqual(first["generated_at"], second["generated_at"])
        self.assertIsNone(self.engine.cached(ttl=0))   # TTL 만료

    def test_missing_data_degrades(self):
        engine = amqs.AmqsNdx(fetch=lambda t: None, cache_file=self.tmp)
        snap = engine.build()
        self.assertEqual(snap["regime"]["regime"], "Unknown")
        self.assertEqual(snap["cash_pct"], 1.0)
        self.assertTrue(snap["warnings"])
        from knot.amqs_page import render_page
        self.assertIn("AMQS-NDX", render_page(snap))   # 그래도 페이지는 그려진다


if __name__ == "__main__":
    unittest.main()
