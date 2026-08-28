#!/usr/bin/env python3
"""Offline self-test for the pair book. No network, no third-party packages.

    python3 lab/test_pairs.py

Synthetic worlds with KNOWN answers, so a regression shows up as a wrong
number rather than as a plausible-looking equity curve:

  * a cointegrated pair (spread is a mean-reverting OU process)
  * a non-cointegrated pair (two independent random walks)

The second case is the important one. Any pairs engine makes money on the
first; the test that matters is that the screen REJECTS the second, because in
a real universe most pairs are the second and the screen is the only thing
standing between you and trading them.
"""
from __future__ import annotations

import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ethena
import hl
from pairs import (LONG_SPREAD, SHORT_SPREAD, ScreenBars, SignalRules, SizingRules,
                   adf_tstat, compute_stats, correlation, decide, half_life,
                   leg_sizes, ols, size_pair)
from pairs_backtest import Costs, Series, align, backtest_pair

FAILS: list = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
    if not cond:
        FAILS.append(f"{name} {detail}")


# --------------------------------------------------------------------------
def make_cointegrated(n=1200, seed=7, hl_bars=18.0, sigma_eq=0.020, drift=0.0002):
    """B is a random walk; A = B * exp(spread) where spread is OU with a known
    half-life. Prices are then genuinely cointegrated in log space."""
    rng = random.Random(seed)
    phi = 0.5 ** (1.0 / hl_bars)                 # AR(1) coeff for target half-life
    eps = sigma_eq * math.sqrt(1 - phi * phi)    # innovation for target stationary sd
    ts, pa, pb = [], [], []
    lb, s = math.log(100.0), 0.0
    t0 = 1_700_000_000_000
    for i in range(n):
        lb += drift + rng.gauss(0, 0.004)
        s = phi * s + rng.gauss(0, eps)
        ts.append(t0 + i * 3_600_000)
        pb.append(math.exp(lb))
        pa.append(math.exp(lb + math.log(1.5) + s))
    return ts, pa, pb


def make_independent(n=1200, seed=11):
    rng = random.Random(seed)
    ts, pa, pb = [], [], []
    la, lb = math.log(100.0), math.log(80.0)
    t0 = 1_700_000_000_000
    for i in range(n):
        la += rng.gauss(0.0001, 0.006)
        lb += rng.gauss(0.0001, 0.006)
        ts.append(t0 + i * 3_600_000)
        pa.append(math.exp(la)); pb.append(math.exp(lb))
    return ts, pa, pb


# --------------------------------------------------------------------------
def test_stats():
    print("\n[stats primitives]")
    xs = [1, 2, 3, 4, 5]
    a, b = ols(xs, [3, 5, 7, 9, 11])            # y = 1 + 2x
    check("ols recovers slope", abs(b - 2.0) < 1e-9, f"beta={b:.6f}")
    check("ols recovers intercept", abs(a - 1.0) < 1e-9, f"alpha={a:.6f}")
    check("correlation of identical series is 1", abs(correlation(xs, xs) - 1) < 1e-9)
    check("correlation of inverted series is -1",
          abs(correlation(xs, [-x for x in xs]) + 1) < 1e-9)

    # Half-life recovery on a clean AR(1).
    rng = random.Random(3)
    target = 20.0
    phi = 0.5 ** (1 / target)
    s, ser = 0.0, []
    for _ in range(6000):
        s = phi * s + rng.gauss(0, 0.01)
        ser.append(s)
    got = half_life(ser)
    check("half-life recovers AR(1) target within 20%",
          abs(got - target) / target < 0.20, f"got={got:.1f} target={target}")

    rw, x = [], 0.0
    for _ in range(2000):
        x += rng.gauss(0, 0.01); rw.append(x)
    check("random walk is not mean-reverting (adf > -2.9)", adf_tstat(rw) > -2.9,
          f"adf={adf_tstat(rw):+.2f}")
    check("OU series is mean-reverting (adf < -2.9)", adf_tstat(ser) < -2.9,
          f"adf={adf_tstat(ser):+.2f}")


def test_screen():
    print("\n[screen: accepts real pairs, rejects fake ones]")
    bars = ScreenBars(min_n=240)

    _, pa, pb = make_cointegrated()
    st = compute_stats("A", "B", pa[-400:], pb[-400:])
    check("cointegrated pair passes the screen", bars.accepts(st),
          bars.reject_reason(st) or st.summary())
    check("hedge ratio near 1.0 by construction", abs(st.beta - 1.0) < 0.35,
          f"beta={st.beta:+.3f}")

    _, ia, ib = make_independent()
    ist = compute_stats("X", "Y", ia[-400:], ib[-400:])
    check("independent random walks are REJECTED", not bars.accepts(ist),
          bars.reject_reason(ist) or "wrongly accepted")


def test_signal():
    print("\n[signal state machine]")
    _, pa, pb = make_cointegrated()
    st = compute_stats("A", "B", pa[-400:], pb[-400:])
    rules = SignalRules(entry_z=2.0, exit_z=0.4, stop_z=4.0)

    # Force a rich-A spread and confirm the side is SHORT_SPREAD.
    st.z = 2.6
    d = decide(st, rules, None, 0, cost_bps=15.0)
    check("z>0 (A rich) opens SHORT_SPREAD",
          d.action == "open" and d.side == SHORT_SPREAD, f"{d.action}/{d.side}")
    st.z = -2.6
    d = decide(st, rules, None, 0, cost_bps=15.0)
    check("z<0 (A cheap) opens LONG_SPREAD",
          d.action == "open" and d.side == LONG_SPREAD, f"{d.action}/{d.side}")
    st.z = 1.0
    check("inside the band does not open",
          decide(st, rules, None, 0, 15.0).action == "none")
    st.z = 5.0
    check("beyond the stop band does not open (regime break, not opportunity)",
          decide(st, rules, None, 0, 15.0).action == "none")

    # Cost gate: a huge cost must suppress an otherwise valid entry.
    st.z = 2.6
    check("entry suppressed when costs exceed the edge",
          decide(st, rules, None, 0, cost_bps=100_000.0).action == "none")


def test_sizing():
    print("\n[sizing and leverage arithmetic]")
    _, pa, pb = make_cointegrated()
    st = compute_stats("A", "B", pa[-400:], pb[-400:])
    sizing = SizingRules(gross_leverage=2.0, max_pairs=4, max_leg_notional_frac=0.60)
    per_leg = size_pair(10_000.0, st, sizing, 0)
    check("per-leg notional splits gross across pairs and legs",
          abs(per_leg - 2_500.0) < 1e-6, f"${per_leg:,.0f}")
    check("a full book of 4 pairs sits at the configured gross, not 4x it",
          abs(per_leg * 2 * 4 / 10_000.0 - 2.0) < 1e-9)

    sz_a, sz_b = leg_sizes(2_500.0, 100.0, 50.0, beta=1.0)
    check("beta=1 gives dollar-neutral legs",
          abs(sz_a * 100 - sz_b * 50) < 1e-6, f"{sz_a * 100:.0f} vs {sz_b * 50:.0f}")
    sz_a, sz_b = leg_sizes(2_500.0, 100.0, 50.0, beta=2.0)
    check("beta=2 doubles leg B notional",
          abs(sz_b * 50 - 5_000.0) < 1e-6, f"${sz_b * 50:,.0f}")


def test_ethena():
    print("\n[ethena collateral and carry]")
    c = ethena.YieldCurve.constant(0.10, haircut=0.0)
    check("APY -> hourly rate", abs(c.hourly_rate_at(0) - 0.10 / 8760) < 1e-15)
    ch = ethena.YieldCurve.constant(0.10, haircut=0.25)
    check("haircut discounts the quoted APY", abs(ch.apy_at(0) - 0.075) < 1e-12,
          f"{ch.apy_at(0):.4f}")

    col = ethena.Collateral(equity=10_000.0, staked_frac=0.8, depeg_haircut=0.02)
    check("only the staked sleeve earns", abs(col.staked - 8_000.0) < 1e-9)
    check("liquid sleeve is the unstaked remainder", abs(col.liquid - 2_000.0) < 1e-9)
    check("usable collateral is haircut", abs(col.usable - 9_800.0) < 1e-9)
    acc = col.yield_accrual(c, 0, hours=8760)
    check("a year of accrual on the staked sleeve = 10% of $8k",
          abs(acc - 800.0) < 1e-6, f"${acc:,.2f}")

    # The core economic claim: carry per notional degrades with leverage.
    f_long, f_short = 0.00002, 0.0   # longs pay
    c1 = ethena.net_carry_bps_per_day(c, 0, f_long, f_short, 1.0, 0.8)
    c4 = ethena.net_carry_bps_per_day(c, 0, f_long, f_short, 4.0, 0.8)
    check("net carry falls as leverage rises when the long leg pays funding",
          c4 < c1, f"1x={c1:+.2f} 4x={c4:+.2f} bps/d")
    czero = ethena.net_carry_bps_per_day(c, 0, 0.0, 0.0, 3.0, 0.8)
    check("with flat funding, carry is positive and leverage-independent",
          czero > 0, f"{czero:+.3f} bps/d")


def test_backtest():
    print("\n[walk-forward backtest]")
    ts, pa, pb = make_cointegrated(n=1600, seed=5)
    sa = Series("A", ts, pa, [0.0] * len(ts))
    sb = Series("B", ts, pb, [0.0] * len(ts))
    res = backtest_pair(sa, sb, equity=10_000.0, lookback=240,
                        curve=ethena.YieldCurve.constant(0.08, haircut=0.0),
                        costs=Costs(taker_fee_bps=2.0, slippage_bps=1.0),
                        rules=SignalRules(entry_z=2.0, exit_z=0.4, stop_z=4.0,
                                          max_hold_bars=240, min_edge_bps=5.0),
                        sizing=SizingRules(gross_leverage=2.0, max_pairs=4),
                        bars_screen=ScreenBars(min_n=240))
    print("   " + res.report().replace("\n", "\n   "))
    check("backtest trades a genuinely cointegrated pair", res.n_trades > 0,
          f"{res.n_trades} trades")
    check("equity curve is marked every bar",
          len(res.equity_curve) >= res.bars, f"{len(res.equity_curve)} pts")
    check("no trade is left open at the end of the sample",
          all(t.reason for t in res.trades))
    check("yield accrued over the sample", res.yield_earned > 0,
          f"${res.yield_earned:,.2f}")
    check("fees were charged", res.fees_paid < 0, f"${res.fees_paid:,.2f}")
    check("a mean-reverting pair is profitable net of all costs",
          res.end_equity > res.start_equity,
          f"${res.start_equity:,.0f} -> ${res.end_equity:,.0f}")

    # Attribution must add up: the equity change is the sum of its parts.
    parts = res.spread_pnl + res.yield_earned + res.funding_paid + res.fees_paid
    delta = res.end_equity - res.start_equity
    check("P&L attribution reconciles to the equity change",
          abs(parts - delta) < max(1.0, abs(delta) * 0.02),
          f"parts={parts:+.2f} delta={delta:+.2f}")

    # Cost sensitivity: brutal costs must kill the trade count, not silently
    # keep printing profits.
    res2 = backtest_pair(sa, sb, equity=10_000.0, lookback=240,
                         curve=ethena.YieldCurve.constant(0.0, haircut=0.0),
                         costs=Costs(taker_fee_bps=250.0, slippage_bps=250.0),
                         rules=SignalRules(min_edge_bps=5.0),
                         bars_screen=ScreenBars(min_n=240))
    check("prohibitive costs suppress trading", res2.n_trades < res.n_trades,
          f"{res2.n_trades} vs {res.n_trades}")

    # Funding drag must actually reduce the result.
    drag = [0.0005] * len(ts)          # long leg bleeds every bar
    res3 = backtest_pair(Series("A", ts, pa, drag), Series("B", ts, pb, [0.0] * len(ts)),
                         equity=10_000.0, lookback=240,
                         curve=ethena.YieldCurve.constant(0.08, haircut=0.0),
                         costs=Costs(taker_fee_bps=2.0, slippage_bps=1.0),
                         rules=SignalRules(min_edge_bps=5.0),
                         bars_screen=ScreenBars(min_n=240))
    check("funding drag reduces net equity vs the zero-funding run",
          res3.end_equity < res.end_equity,
          f"${res3.end_equity:,.0f} vs ${res.end_equity:,.0f}")

    # The no-edge case.
    ts2, ia, ib = make_independent(n=1600, seed=13)
    res4 = backtest_pair(Series("X", ts2, ia, [0.0] * len(ts2)),
                         Series("Y", ts2, ib, [0.0] * len(ts2)),
                         equity=10_000.0, lookback=240,
                         curve=ethena.YieldCurve.constant(0.08, haircut=0.0),
                         costs=Costs(), bars_screen=ScreenBars(min_n=240))
    check("screen keeps the engine out of an uncointegrated pair",
          res4.n_trades == 0, f"{res4.n_trades} trades on random walks")


def test_alignment():
    print("\n[bar alignment]")
    a = Series("A", [1, 2, 3, 4, 5], [10, 11, 12, 13, 14])
    b = Series("B", [2, 3, 5], [20, 21, 22])
    ra, rb = align(a, b)
    check("align inner-joins on timestamp", ra.ts == [2, 3, 5], f"{ra.ts}")
    check("aligned closes track their own series",
          ra.close == [11, 12, 14] and rb.close == [20, 21, 22])
    check("aligned series have equal length", len(ra.close) == len(rb.close))


def test_hl_rounding():
    print("\n[hyperliquid wire correctness]")
    m = hl.Market(name="AAPL", dex="eq", asset=110_003, sz_decimals=2, max_leverage=5)
    check("qualified name namespaces the dex", m.qualified == "eq:AAPL", m.qualified)
    # 5 sig figs and <= (6 - szDecimals) = 4 decimals.
    check("px rounds to 5 significant figures", m.round_px(123.456789) == 123.46,
          str(m.round_px(123.456789)))
    check("px respects the decimal cap", m.round_px(0.123456789) == 0.1235,
          str(m.round_px(0.123456789)))
    check("integer px is exempt from the sig-fig rule", m.round_px(123456.0) == 123456.0,
          str(m.round_px(123456.0)))
    check("size rounds to szDecimals", m.round_sz(1.23456) == 1.23, str(m.round_sz(1.23456)))

    oi = hl.OrderIntent(m, True, 1.23456, 123.456789)
    w = oi.wire()
    check("wire carries the resolved asset index", w["a"] == 110_003, str(w["a"]))
    check("wire price is a trimmed string", w["p"] == "123.46", w["p"])
    check("wire size is a trimmed string", w["s"] == "1.23", w["s"])
    check("wire marks the buy side", w["b"] is True)

    buy = hl.slippage_px(100.0, True, 0.001, m)
    sell = hl.slippage_px(100.0, False, 0.001, m)
    check("buy slippage prices up, sell prices down", buy > 100.0 > sell,
          f"{buy} / {sell}")

    # HIP-3 offsets are the detail most likely to send an order to the wrong
    # market, so pin the arithmetic.
    check("builder dex 0 starts at 110000", hl.BUILDER_BASE == 110_000)
    check("builder dexs are 10000 apart", hl.DEX_STRIDE == 10_000)


def test_executor_gate():
    print("\n[execution safety gate]")
    saved = os.environ.pop(hl.Executor.LIVE_ENV, None)
    try:
        ex = hl.Executor(live=False)
        m = hl.Market("AAPL", "eq", 110_003, 2, 5)
        res = ex.send([hl.OrderIntent(m, True, 1.0, 100.0)])
        check("dry-run returns without sending", res and res[0]["status"] == "dry-run")
        raised = False
        try:
            hl.Executor(live=True)
        except hl.HLError:
            raised = True
        check(f"live refuses without {hl.Executor.LIVE_ENV}=1", raised)
    finally:
        if saved is not None:
            os.environ[hl.Executor.LIVE_ENV] = saved


def test_risk():
    print("\n[risk limits]")
    from pairs import RiskLimits, RiskState, check_risk
    lim = RiskLimits(max_gross_leverage=3.0, max_margin_ratio=0.5,
                     max_daily_loss_frac=0.05, max_drawdown_frac=0.15,
                     min_equity=250.0)
    st = RiskState(); st.update(10_000.0, new_day=True)
    check("healthy book is not halted", check_risk(10_000, 2.0, 0.3, lim, st) is None)
    check("over-leverage halts", check_risk(10_000, 3.5, 0.3, lim, st) is not None)
    check("margin ratio breach halts", check_risk(10_000, 2.0, 0.7, lim, st) is not None)
    check("daily loss breach halts", check_risk(9_400, 2.0, 0.3, lim, st) is not None)
    st.update(20_000.0, new_day=False)
    check("drawdown from peak halts", check_risk(16_000, 1.0, 0.1, lim, st) is not None)
    check("equity floor halts", check_risk(100, 1.0, 0.1, lim, st) is not None)


def test_spec_matches_code():
    """pairs.yaml is the spec of record; the dataclass defaults are what
    actually runs. If those two drift, the documented strategy and the traded
    strategy are different strategies -- so pin them against each other."""
    print("\n[pairs.yaml matches code defaults]")
    from pairs import RiskLimits, ScreenBars, SignalRules, SizingRules
    from pairs_backtest import Costs

    spec_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             os.pardir, "pairs.yaml")
    if not os.path.exists(spec_path):
        check("pairs.yaml exists", False, spec_path)
        return

    # Flat "key: number" scrape -- enough for the scalars we need to pin.
    spec = {}
    for raw in open(spec_path):
        line = raw.split("#")[0].strip()
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k, v = k.strip().lstrip("- ").strip(), v.strip()
        if not v:
            continue
        try:
            spec[k] = float(v)
        except ValueError:
            pass

    sb, sig, sz, cost, risk = (ScreenBars(), SignalRules(), SizingRules(),
                               Costs(), RiskLimits())
    pairs_to_pin = [
        ("lookback_bars", sb.min_n), ("min_n", sb.min_n),
        ("min_abs_corr", sb.min_abs_corr),
        ("min_half_life", sb.min_half_life), ("max_half_life", sb.max_half_life),
        ("max_adf", sb.max_adf), ("min_stability", sb.min_stability),
        ("min_sigma_bps", sb.min_sigma_bps),
        ("beta_min", sb.beta_range[0]), ("beta_max", sb.beta_range[1]),
        ("entry_z", sig.entry_z), ("exit_z", sig.exit_z), ("stop_z", sig.stop_z),
        ("max_hold_bars", sig.max_hold_bars), ("min_edge_bps", sig.min_edge_bps),
        ("gross_leverage", sz.gross_leverage), ("max_pairs", sz.max_pairs),
        ("max_leg_notional_frac", sz.max_leg_notional_frac),
        ("vol_target_bps", sz.vol_target_bps),
        ("taker_fee_bps", cost.taker_fee_bps), ("slippage_bps", cost.slippage_bps),
        ("max_gross_leverage", risk.max_gross_leverage),
        ("max_margin_ratio", risk.max_margin_ratio),
        ("max_daily_loss_frac", risk.max_daily_loss_frac),
        ("max_drawdown_frac", risk.max_drawdown_frac),
        ("min_equity_usd", risk.min_equity),
    ]
    missing = [k for k, _ in pairs_to_pin if k not in spec]
    check("every pinned key is present in pairs.yaml", not missing, str(missing))
    bad = [f"{k}: yaml={spec[k]} code={v}"
           for k, v in pairs_to_pin if k in spec and abs(spec[k] - float(v)) > 1e-9]
    check("pairs.yaml scalars equal the code defaults", not bad, "; ".join(bad))

    # Collateral defaults live on the Collateral/YieldCurve dataclasses.
    col = ethena.Collateral(equity=1.0)
    coll_pins = [("staked_frac", col.staked_frac),
                 ("depeg_haircut", col.depeg_haircut),
                 ("unstake_cooldown_hours", col.unstake_cooldown_hours),
                 ("apy_haircut", ethena.YieldCurve.constant(0.0).haircut)]
    bad2 = [f"{k}: yaml={spec.get(k)} code={v}"
            for k, v in coll_pins if k in spec and abs(spec[k] - float(v)) > 1e-9]
    check("collateral defaults match pairs.yaml", not bad2, "; ".join(bad2))


# --------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 70)
    print("Ethena/Hyperliquid equity pair book -- offline self-test")
    print("=" * 70)
    test_stats()
    test_screen()
    test_signal()
    test_sizing()
    test_ethena()
    test_alignment()
    test_backtest()
    test_hl_rounding()
    test_executor_gate()
    test_risk()
    test_spec_matches_code()
    print("\n" + "=" * 70)
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S):")
        for f in FAILS:
            print(f"  - {f}")
        raise SystemExit(1)
    print("all checks passed")
