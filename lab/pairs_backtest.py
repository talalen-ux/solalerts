#!/usr/bin/env python3
"""Walk-forward backtester for the Ethena-collateralised equity pair book.

The four terms that decide whether this strategy makes money, all on one
hourly clock:

    spread P&L  +  sUSDe yield on posted margin
                -  net perp funding  -  fees  -  slippage

Most pairs backtests model term one and quietly assume the rest are noise. For
a market-neutral book they are not noise -- they are the entire result. On a
2x-gross book, funding on $2 of notional against yield on $1 of equity is a
larger number than the spread edge it is trying to protect.

Mechanics kept honest:
  * Walk-forward. The hedge ratio and z-score for bar t are refit on the
    trailing `lookback` bars ending at t. Nothing is fit once over the sample.
  * Entry fills at bar t's close with slippage, from a signal computed on data
    through bar t. No same-bar-close-to-open magic.
  * Funding accrues on the actual signed notional, hourly, on the bars held.
  * Yield accrues on the staked sleeve of equity every bar, whether or not a
    position is open -- that is the point of the collateral choice.
  * Equity is marked every bar, so drawdown/halt logic sees the same series a
    live account would.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from ethena import Collateral, YieldCurve
from pairs import (LONG_SPREAD, PairPosition, RiskLimits, RiskState, ScreenBars,
                   SignalRules, SizingRules, check_risk, compute_stats, decide,
                   size_pair)

BPS = 1e-4


@dataclass
class Costs:
    taker_fee_bps: float = 4.5      # HIP-3 equity perps run wider than core
    slippage_bps: float = 3.0

    @property
    def per_leg_round_trip_bps(self) -> float:
        """Enter + exit, one leg."""
        return 2.0 * (self.taker_fee_bps + self.slippage_bps)

    @property
    def pair_round_trip_bps(self) -> float:
        """Enter + exit, both legs -- what a signal must actually clear."""
        return 2.0 * self.per_leg_round_trip_bps


@dataclass
class Trade:
    pair: str
    side: str
    open_bar: int
    close_bar: int
    open_ts: int
    close_ts: int
    entry_z: float
    exit_z: float
    notional_per_leg: float
    spread_pnl: float
    funding_pnl: float
    fees: float
    net_pnl: float
    reason: str

    @property
    def bars_held(self) -> int:
        return self.close_bar - self.open_bar


@dataclass
class Series:
    """One market's aligned history."""
    name: str
    ts: List[int]
    close: List[float]
    funding: List[float] = field(default_factory=list)   # hourly rate per bar

    def funding_at(self, i: int) -> float:
        return self.funding[i] if i < len(self.funding) else 0.0


def align(a: Series, b: Series) -> Tuple[Series, Series]:
    """Inner-join two series on timestamp. Unaligned bars are the classic way
    a pair backtest invents edge -- a stale print on one leg reads as a spread
    dislocation that was never tradable."""
    idx_b = {t: i for i, t in enumerate(b.ts)}
    ts, ca, cb, fa, fb = [], [], [], [], []
    for i, t in enumerate(a.ts):
        j = idx_b.get(t)
        if j is None:
            continue
        ts.append(t)
        ca.append(a.close[i]); cb.append(b.close[j])
        fa.append(a.funding_at(i)); fb.append(b.funding_at(j))
    return (Series(a.name, ts, ca, fa), Series(b.name, ts, cb, fb))


@dataclass
class BacktestResult:
    pair: str
    bars: int
    trades: List[Trade]
    equity_curve: List[Tuple[int, float]]
    start_equity: float
    end_equity: float
    yield_earned: float
    funding_paid: float
    fees_paid: float
    spread_pnl: float
    halted: Optional[str] = None
    rejected: Optional[str] = None

    # -- metrics ----------------------------------------------------------
    @property
    def n_trades(self) -> int:
        return len(self.trades)

    @property
    def total_return(self) -> float:
        return (self.end_equity / self.start_equity - 1.0) if self.start_equity else 0.0

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        return sum(1 for t in self.trades if t.net_pnl > 0) / len(self.trades)

    @property
    def avg_bars_held(self) -> float:
        return mean_or0([t.bars_held for t in self.trades])

    @property
    def max_drawdown(self) -> float:
        peak, mdd = 0.0, 0.0
        for _, e in self.equity_curve:
            peak = max(peak, e)
            if peak > 0:
                mdd = max(mdd, (peak - e) / peak)
        return mdd

    def sharpe(self, bars_per_year: float = 6_552.0) -> float:
        """Annualised Sharpe on bar-over-bar equity returns.

        Default assumes ~6.5h equity sessions x 252 days: equity perps trade
        nearly 24/7 on Hyperliquid, but the underlying only prices during the
        cash session, so annualising on 8760 overstates the independent-sample
        count. Pass your own if your bars differ.
        """
        rets = []
        for (_, a), (_, b) in zip(self.equity_curve, self.equity_curve[1:]):
            if a > 0:
                rets.append(b / a - 1.0)
        if len(rets) < 3:
            return 0.0
        m = sum(rets) / len(rets)
        sd = math.sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1))
        if sd <= 0:
            return 0.0
        return (m / sd) * math.sqrt(bars_per_year)

    def report(self) -> str:
        if self.rejected:
            return f"{self.pair}: REJECTED -- {self.rejected}"
        lines = [
            f"{self.pair}: {self.n_trades} trades over {self.bars} bars",
            f"  equity   ${self.start_equity:,.0f} -> ${self.end_equity:,.0f}  "
            f"({self.total_return:+.2%})  maxDD {self.max_drawdown:.2%}  "
            f"Sharpe {self.sharpe():.2f}",
            f"  win rate {self.win_rate:.1%}   avg hold {self.avg_bars_held:.0f} bars",
            f"  attribution: spread {self.spread_pnl:+,.0f} | yield {self.yield_earned:+,.0f} | "
            f"funding {self.funding_paid:+,.0f} | fees {self.fees_paid:+,.0f}",
        ]
        if self.halted:
            lines.append(f"  HALTED: {self.halted}")
        return "\n".join(lines)


def mean_or0(xs: Sequence[float]) -> float:
    return (sum(xs) / len(xs)) if xs else 0.0


def backtest_pair(
    sa: Series,
    sb: Series,
    *,
    equity: float = 10_000.0,
    lookback: int = 240,
    curve: Optional[YieldCurve] = None,
    costs: Optional[Costs] = None,
    rules: Optional[SignalRules] = None,
    sizing: Optional[SizingRules] = None,
    bars_screen: Optional[ScreenBars] = None,
    limits: Optional[RiskLimits] = None,
    staked_frac: float = 0.80,
    depeg_haircut: float = 0.02,
    bars_per_day: float = 24.0,
    screen_at_entry: bool = True,
) -> BacktestResult:
    """Walk forward over the aligned pair. One position at a time per pair."""
    curve = curve or YieldCurve.constant(0.08)
    costs = costs or Costs()
    rules = rules or SignalRules()
    sizing = sizing or SizingRules()
    bars_screen = bars_screen or ScreenBars()
    limits = limits or RiskLimits()

    sa, sb = align(sa, sb)
    pair_name = f"{sa.name}/{sb.name}"
    n = len(sa.ts)
    coll = Collateral(equity=equity, staked_frac=staked_frac, depeg_haircut=depeg_haircut)
    risk = RiskState()
    risk.update(coll.equity, new_day=True)

    trades: List[Trade] = []
    curve_pts: List[Tuple[int, float]] = []
    pos: Optional[PairPosition] = None
    open_meta: Dict[str, float] = {}
    tot_yield = tot_funding = tot_fees = tot_spread = 0.0
    halted: Optional[str] = None

    if n < lookback + 10:
        return BacktestResult(pair_name, n, [], [], equity, equity, 0, 0, 0, 0,
                              rejected=f"only {n} aligned bars, need {lookback + 10}")

    hours_per_bar = 24.0 / bars_per_day
    last_day = -1

    for i in range(lookback, n):
        ts = sa.ts[i]
        px_a, px_b = sa.close[i], sb.close[i]

        # --- carry accrues every bar, position or not --------------------
        acc = coll.yield_accrual(curve, ts, hours=hours_per_bar)
        coll.credit(acc)
        tot_yield += acc

        # --- funding on any open position --------------------------------
        if pos is not None:
            # side long_spread = long A / short B. Positive funding => longs pay.
            sign_a = 1.0 if pos.side == LONG_SPREAD else -1.0
            sign_b = -sign_a
            ntl_a = pos.notional_per_leg
            ntl_b = pos.notional_per_leg * abs(pos.beta)
            f = -(sign_a * ntl_a * sa.funding_at(i) + sign_b * ntl_b * sb.funding_at(i))
            f *= hours_per_bar
            coll.credit(f)
            tot_funding += f
            open_meta["funding"] = open_meta.get("funding", 0.0) + f

        # --- mark equity --------------------------------------------------
        mtm = 0.0
        if pos is not None:
            mtm = _spread_pnl(pos, px_a, px_b)
        equity_now = coll.equity + mtm
        day = int(ts // 86_400_000)
        risk.update(equity_now, new_day=(day != last_day and last_day >= 0))
        last_day = day
        curve_pts.append((ts, equity_now))

        # --- stats on the trailing window ending at i ---------------------
        wa = sa.close[i - lookback + 1: i + 1]
        wb = sb.close[i - lookback + 1: i + 1]
        st = compute_stats(sa.name, sb.name, wa, wb)

        d = decide(st, rules, pos, i, costs.pair_round_trip_bps)

        # --- close --------------------------------------------------------
        if pos is not None and d.action == "close":
            sp = _spread_pnl(pos, px_a, px_b)
            exit_fees = _fees(pos, px_a, px_b, costs)
            realized = sp - exit_fees
            coll.credit(realized)
            tot_spread += sp
            tot_fees += exit_fees
            trades.append(Trade(
                pair=pair_name, side=pos.side, open_bar=pos.entry_bar, close_bar=i,
                open_ts=int(open_meta.get("ts", ts)), close_ts=ts,
                entry_z=pos.entry_z, exit_z=d.z,
                notional_per_leg=pos.notional_per_leg,
                spread_pnl=sp, funding_pnl=open_meta.get("funding", 0.0),
                fees=exit_fees + open_meta.get("entry_fees", 0.0),
                net_pnl=realized + open_meta.get("funding", 0.0) - open_meta.get("entry_fees", 0.0),
                reason=d.reason,
            ))
            pos, open_meta = None, {}

        # --- risk gate blocks NEW risk only -------------------------------
        gross = 0.0 if pos is None else (
            pos.notional_per_leg * (1 + abs(pos.beta)) / max(equity_now, 1e-9))
        margin_ratio = gross / max(sizing.gross_leverage, 1e-9) * 0.5
        halt = check_risk(equity_now, gross, margin_ratio, limits, risk)
        if halt:
            halted = halt
            continue

        # --- open ---------------------------------------------------------
        if pos is None and d.action == "open":
            if screen_at_entry:
                why = bars_screen.reject_reason(st)
                if why:
                    continue
            coll.equity = equity_now  # realized-only base; no open position here
            notional = size_pair(coll.usable, st, sizing, n_open=0)
            if notional <= 0:
                continue
            entry_fees = notional * (1 + abs(st.beta)) * (
                costs.taker_fee_bps + costs.slippage_bps) * BPS
            coll.credit(-entry_fees)
            tot_fees += entry_fees
            pos = PairPosition(
                side=d.side, entry_z=st.z, entry_bar=i, beta=st.beta,
                notional_per_leg=notional, entry_px_a=px_a, entry_px_b=px_b,
            )
            open_meta = {"ts": ts, "entry_fees": entry_fees, "funding": 0.0}

    # --- force-close at the end so the result is not flattered by an open
    #     winner that never had to pay its exit costs ------------------------
    if pos is not None:
        i = n - 1
        px_a, px_b = sa.close[i], sb.close[i]
        sp = _spread_pnl(pos, px_a, px_b)
        exit_fees = _fees(pos, px_a, px_b, costs)
        coll.credit(sp - exit_fees)
        tot_spread += sp
        tot_fees += exit_fees
        trades.append(Trade(
            pair=pair_name, side=pos.side, open_bar=pos.entry_bar, close_bar=i,
            open_ts=int(open_meta.get("ts", sa.ts[i])), close_ts=sa.ts[i],
            entry_z=pos.entry_z, exit_z=0.0, notional_per_leg=pos.notional_per_leg,
            spread_pnl=sp, funding_pnl=open_meta.get("funding", 0.0),
            fees=exit_fees + open_meta.get("entry_fees", 0.0),
            net_pnl=sp - exit_fees + open_meta.get("funding", 0.0) - open_meta.get("entry_fees", 0.0),
            reason="end of sample (force-closed)",
        ))
        curve_pts.append((sa.ts[i], coll.equity))

    return BacktestResult(
        pair=pair_name, bars=n - lookback, trades=trades, equity_curve=curve_pts,
        start_equity=equity, end_equity=(curve_pts[-1][1] if curve_pts else equity),
        yield_earned=tot_yield, funding_paid=tot_funding, fees_paid=-tot_fees,
        spread_pnl=tot_spread, halted=halted,
    )


def _spread_pnl(pos: PairPosition, px_a: float, px_b: float) -> float:
    """Mark-to-market of the two legs, in dollars.

    Long-spread = long A, short beta-weighted B. Returns are taken in simple
    terms off the entry prices; the beta weight is applied to leg B's notional
    exactly as it was at entry, matching how the contracts were actually sized.
    """
    ra = px_a / pos.entry_px_a - 1.0
    rb = px_b / pos.entry_px_b - 1.0
    sign = 1.0 if pos.side == LONG_SPREAD else -1.0
    return sign * pos.notional_per_leg * (ra - abs(pos.beta) * rb)


def _fees(pos: PairPosition, px_a: float, px_b: float, costs: Costs) -> float:
    """Exit cost on the notional as it stands now, not as it was at entry --
    a leg that doubled costs twice as much to close."""
    ntl_a = pos.notional_per_leg * (px_a / pos.entry_px_a)
    ntl_b = pos.notional_per_leg * abs(pos.beta) * (px_b / pos.entry_px_b)
    return (ntl_a + ntl_b) * (costs.taker_fee_bps + costs.slippage_bps) * BPS
