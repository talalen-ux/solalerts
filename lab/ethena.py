#!/usr/bin/env python3
"""Ethena collateral layer.

The reason this file exists: a market-neutral equity pair earns nothing from
direction by construction. Its entire P&L is (spread convergence) + (collateral
yield) - (funding) - (fees) - (slippage). Three of those five terms are carry,
so a backtest that models only the spread is not measuring the strategy -- it is
measuring a quarter of it, and always the flattering quarter.

sUSDe changes the sign of the idle-margin term. Margin posted as sUSDe accrues
Ethena's staking yield while it sits as collateral, so the strategy's hurdle
rate is not zero -- it is *negative*: a pair book that breaks even on spread
still earns the staking APY on posted margin, minus net funding.

That cuts both ways, and the asymmetry is the point:

  * The yield accrues on POSTED MARGIN (equity), not on notional. Levering 3x
    does not triple the yield -- it triples the funding drag against a fixed
    yield base. Carry per unit of notional therefore *falls* with leverage.
    `net_carry_bps_per_day` below is what makes that visible.
  * sUSDe yield is floating and has printed near zero (and, in stressed
    regimes, negative funding for Ethena itself). Backtesting at a constant
    "current APY" is the single most common way to manufacture a fake edge.
    Hence `YieldCurve`, which takes a *series*, and `haircut`, which defaults
    to a conservative discount rather than to trust.
  * Collateral is not riskless. A depeg or redemption queue hits the margin
    base while positions stay open. `depeg_haircut` prices that into usable
    collateral rather than pretending it away.

Offline-safe: every network call has an explicit fallback and the module never
raises on a dead feed -- it degrades to the configured assumption and says so.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

HOURS_PER_YEAR = 8760.0

# Public Ethena yield endpoint. Reachability varies by network policy; every
# caller handles failure by falling back to an explicit assumption.
ETHENA_YIELD_URL = "https://ethena.fi/api/yields/protocol-and-staking-yield"


# --------------------------------------------------------------------------
# yield
# --------------------------------------------------------------------------
def fetch_staking_apy(timeout: float = 10.0) -> Optional[float]:
    """Current sUSDe staking APY as a fraction (0.09 == 9%). None if the feed
    is unreachable -- callers must supply their own assumption, loudly."""
    try:
        req = urllib.request.Request(
            ETHENA_YIELD_URL, headers={"Accept": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
    except Exception:
        return None
    # Endpoint has shipped both a bare object and a single-element list.
    if isinstance(data, list):
        if not data:
            return None
        data = data[0]
    if not isinstance(data, dict):
        return None
    for key in ("stakingYield", "staking_yield"):
        node = data.get(key)
        if isinstance(node, dict) and node.get("value") is not None:
            v = float(node["value"])
            break
        if isinstance(node, (int, float)):
            v = float(node)
            break
    else:
        return None
    # Endpoint reports percent (9.1); normalise to a fraction.
    return v / 100.0 if v > 1.0 else v


@dataclass
class YieldCurve:
    """A time series of sUSDe APY, so a backtest can pay the yield that
    actually existed rather than today's number retro-applied to history.

    `points` is [(timestamp_ms, apy_fraction)], ascending. A single point
    degenerates to a constant curve, which is honest as long as you know that
    is what you asked for -- `is_constant` reports it.
    """
    points: List[Tuple[int, float]] = field(default_factory=list)
    haircut: float = 0.25   # discount applied to every quoted APY

    def __post_init__(self) -> None:
        self.points = sorted(self.points)
        if not self.points:
            raise ValueError("YieldCurve needs at least one point")
        if not 0.0 <= self.haircut < 1.0:
            raise ValueError("haircut must be in [0, 1)")

    @classmethod
    def constant(cls, apy: float, haircut: float = 0.25) -> "YieldCurve":
        return cls(points=[(0, apy)], haircut=haircut)

    @classmethod
    def live_or(cls, fallback_apy: float, haircut: float = 0.25) -> Tuple["YieldCurve", bool]:
        """(curve, is_live). Falls back to `fallback_apy` on a dead feed."""
        apy = fetch_staking_apy()
        if apy is None:
            return cls.constant(fallback_apy, haircut), False
        return cls.constant(apy, haircut), True

    @property
    def is_constant(self) -> bool:
        return len(self.points) == 1

    def apy_at(self, ts_ms: int) -> float:
        """Step-function lookup, haircut applied. Before the first point we
        hold the first value flat rather than extrapolating to zero."""
        raw = self.points[0][1]
        for t, v in self.points:
            if t <= ts_ms:
                raw = v
            else:
                break
        return raw * (1.0 - self.haircut)

    def hourly_rate_at(self, ts_ms: int) -> float:
        """Per-hour simple rate, matching Hyperliquid's hourly funding clock so
        the two carry terms can be netted on the same grid."""
        return self.apy_at(ts_ms) / HOURS_PER_YEAR

    def accrue(self, principal: float, ts_ms: int, hours: float = 1.0) -> float:
        return principal * self.hourly_rate_at(ts_ms) * hours


# --------------------------------------------------------------------------
# collateral
# --------------------------------------------------------------------------
@dataclass
class Collateral:
    """The USDe/sUSDe margin base behind the book.

    `staked_frac` is the share of equity held as sUSDe (yield-bearing) rather
    than plain USDe. It is rarely 1.0 in practice: perp margin needs a liquid
    unstaked buffer to absorb losses and top-ups without unstaking through a
    cooldown window, and sUSDe's cooldown is exactly the thing that bites in
    the drawdown where you need the buffer.
    """
    equity: float
    staked_frac: float = 0.80
    depeg_haircut: float = 0.02      # usable collateral discount for peg risk
    unstake_cooldown_hours: float = 168.0   # 7d cooldown; liquidity, not yield

    def __post_init__(self) -> None:
        if self.equity < 0:
            raise ValueError("equity must be non-negative")
        if not 0.0 <= self.staked_frac <= 1.0:
            raise ValueError("staked_frac must be in [0, 1]")
        if not 0.0 <= self.depeg_haircut < 1.0:
            raise ValueError("depeg_haircut must be in [0, 1)")

    @property
    def staked(self) -> float:
        return self.equity * self.staked_frac

    @property
    def liquid(self) -> float:
        """Unstaked USDe -- the only part available inside the cooldown."""
        return self.equity * (1.0 - self.staked_frac)

    @property
    def usable(self) -> float:
        """Collateral value after the peg haircut. This, not `equity`, is what
        position sizing is allowed to lever against."""
        return self.equity * (1.0 - self.depeg_haircut)

    def yield_accrual(self, curve: YieldCurve, ts_ms: int, hours: float = 1.0) -> float:
        """Yield earned over `hours`. Only the staked sleeve earns."""
        return curve.accrue(self.staked, ts_ms, hours)

    def credit(self, amount: float) -> None:
        """Apply P&L / yield to equity, keeping the staked/liquid split."""
        self.equity = max(0.0, self.equity + amount)


# --------------------------------------------------------------------------
# carry
# --------------------------------------------------------------------------
def net_carry_bps_per_day(
    curve: YieldCurve,
    ts_ms: int,
    long_funding_hourly: float,
    short_funding_hourly: float,
    gross_leverage: float,
    staked_frac: float = 0.80,
) -> float:
    """Daily net carry in bps of EQUITY for a dollar-neutral pair.

    Sign convention (Hyperliquid): a positive funding rate means longs pay
    shorts. A dollar-neutral pair is long one market and short the other, so
    per unit of *per-leg* notional the funding P&L is
    (short_leg_rate - long_leg_rate); with gross leverage L the notional per
    leg is L/2 of equity.

    The yield term does not scale with L and the funding term does. That is the
    whole economic story of this book in one expression -- print it before
    choosing leverage, not after.
    """
    yield_hourly = curve.hourly_rate_at(ts_ms) * staked_frac
    funding_hourly = (short_funding_hourly - long_funding_hourly) * (gross_leverage / 2.0)
    return (yield_hourly + funding_hourly) * 24.0 * 10_000.0


def breakeven_spread_move_bps(
    curve: YieldCurve,
    ts_ms: int,
    holding_days: float,
    taker_fee_bps: float,
    slippage_bps: float,
    gross_leverage: float,
    long_funding_hourly: float = 0.0,
    short_funding_hourly: float = 0.0,
    staked_frac: float = 0.80,
) -> float:
    """How far the spread must converge (bps of per-leg notional) just to break
    even, after round-trip costs on both legs and net carry over the hold.

    A negative answer means carry alone pays for the trade -- the sUSDe case
    the whole design is chasing. Positive means the spread has to do work.
    """
    round_trip_cost_bps = 2.0 * 2.0 * (taker_fee_bps + slippage_bps)
    carry_bps_equity = net_carry_bps_per_day(
        curve, ts_ms, long_funding_hourly, short_funding_hourly,
        gross_leverage, staked_frac,
    ) * holding_days
    # Convert carry from bps-of-equity to bps-of-per-leg-notional.
    per_leg_mult = max(gross_leverage / 2.0, 1e-9)
    return round_trip_cost_bps - carry_bps_equity / per_leg_mult


def describe(curve: YieldCurve, collateral: Collateral, ts_ms: int) -> str:
    apy = curve.apy_at(ts_ms)
    return (
        f"collateral: equity ${collateral.equity:,.0f} "
        f"({collateral.staked_frac:.0%} sUSDe / {1 - collateral.staked_frac:.0%} USDe), "
        f"usable ${collateral.usable:,.0f} after {collateral.depeg_haircut:.1%} depeg haircut | "
        f"sUSDe APY {apy:.2%} post-{curve.haircut:.0%}-haircut"
        f"{' [CONSTANT ASSUMPTION]' if curve.is_constant else ''}"
    )
