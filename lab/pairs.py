#!/usr/bin/env python3
"""Pair statistics and the signal state machine. Pure stdlib.

Design commitments, each one a failure mode this repo has already paid for in
the Solana book and which reappears verbatim in stat-arb:

  * NO LOOKAHEAD. Every statistic used to trade bar t is computed from data
    strictly through bar t. The hedge ratio is re-estimated on a trailing
    window, not fit once over the whole sample. In-sample beta is the
    stat-arb equivalent of fitting a filter to its own backtest -- it produces
    a beautiful equity curve and no money.
  * WEEK-STABILITY OVER HEADLINE FIT. A pair that only cointegrates in one
    regime is regime-fit. `stability` scores per-window consistency and the
    screen rejects on it, mirroring the SHIELD bar that a leg must improve in
    EVERY week with n>=80.
  * COST-AWARE ENTRY. An entry threshold that ignores the round-trip cost of
    two perp legs will trade noise profitably on paper only. `min_edge_bps`
    forces the expected convergence to clear costs before a signal fires.
  * STATIONARITY IS A GATE, NOT A DECORATION. Half-life must be finite and
    inside the holding horizon; a spread with a 400-bar half-life is a
    directional bet wearing a market-neutral costume.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

# --------------------------------------------------------------------------
# small-stats toolkit (stdlib only)
# --------------------------------------------------------------------------
def mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def stdev(xs: Sequence[float]) -> float:
    """Sample standard deviation."""
    n = len(xs)
    if n < 2:
        return 0.0
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def correlation(xs: Sequence[float], ys: Sequence[float]) -> float:
    n = min(len(xs), len(ys))
    if n < 2:
        return 0.0
    xs, ys = xs[-n:], ys[-n:]
    mx, my = mean(xs), mean(ys)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx <= 0 or sy <= 0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def ols(xs: Sequence[float], ys: Sequence[float]) -> Tuple[float, float]:
    """y = alpha + beta*x -> (alpha, beta)."""
    n = min(len(xs), len(ys))
    if n < 2:
        return 0.0, 0.0
    xs, ys = xs[-n:], ys[-n:]
    mx, my = mean(xs), mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return my, 0.0
    beta = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return my - beta * mx, beta


def log_returns(px: Sequence[float]) -> List[float]:
    out = []
    for a, b in zip(px, px[1:]):
        if a > 0 and b > 0:
            out.append(math.log(b / a))
    return out


def half_life(spread: Sequence[float]) -> float:
    """Ornstein-Uhlenbeck half-life via the AR(1) regression
    d_s(t) = a + lam * s(t-1). Returns inf when the series is not
    mean-reverting (lam >= 0), which is the answer we want to gate on.
    """
    if len(spread) < 8:
        return float("inf")
    lagged = list(spread[:-1])
    delta = [b - a for a, b in zip(spread, spread[1:])]
    _, lam = ols(lagged, delta)
    if lam >= -1e-9:
        return float("inf")
    return -math.log(2.0) / math.log1p(lam) if lam > -1.0 else 1.0


def adf_tstat(spread: Sequence[float]) -> float:
    """t-statistic on lam in the AR(1) regression above -- a no-lag
    Dickey-Fuller. More negative = more strongly mean-reverting. Rule of
    thumb: < -2.9 is roughly 5% significance.

    This is deliberately the *simple* DF, not augmented: with no scipy we
    cannot get exact critical values anyway, and a lag-augmented version would
    imply a precision this estimate does not have. It is used as a screen, not
    as a p-value.
    """
    n = len(spread)
    if n < 12:
        return 0.0
    x = list(spread[:-1])
    y = [b - a for a, b in zip(spread, spread[1:])]
    alpha, lam = ols(x, y)
    resid = [yi - (alpha + lam * xi) for xi, yi in zip(x, y)]
    dof = len(x) - 2
    if dof <= 0:
        return 0.0
    sse = sum(r * r for r in resid)
    mx = mean(x)
    sxx = sum((xi - mx) ** 2 for xi in x)
    if sxx <= 0 or sse <= 0:
        return 0.0
    se = math.sqrt((sse / dof) / sxx)
    return lam / se if se > 0 else 0.0


# --------------------------------------------------------------------------
# the pair
# --------------------------------------------------------------------------
@dataclass
class PairStats:
    """Everything decided about a pair from a trailing window."""
    a: str
    b: str
    n: int
    beta: float             # hedge ratio: 1 unit A hedged by beta units B (log space)
    alpha: float
    corr: float
    spread: List[float]
    z: float
    sigma: float
    hl: float
    adf: float
    stability: float        # share of sub-windows that stay mean-reverting

    @property
    def ok_basic(self) -> bool:
        return self.n >= 30 and self.sigma > 0 and math.isfinite(self.hl)

    def summary(self) -> str:
        hl = f"{self.hl:.1f}" if math.isfinite(self.hl) else "inf"
        return (f"{self.a}/{self.b}  n={self.n} beta={self.beta:+.3f} corr={self.corr:+.2f} "
                f"z={self.z:+.2f} hl={hl} adf={self.adf:+.2f} stab={self.stability:.2f}")


def build_spread(px_a: Sequence[float], px_b: Sequence[float], beta: float, alpha: float) -> List[float]:
    """log(A) - (alpha + beta*log(B)). Log space so the hedge is ratio-based
    and stays neutral as prices drift -- a dollar-space spread silently
    re-levers itself as the legs move."""
    n = min(len(px_a), len(px_b))
    out = []
    for a, b in zip(px_a[-n:], px_b[-n:]):
        if a > 0 and b > 0:
            out.append(math.log(a) - (alpha + beta * math.log(b)))
    return out


def compute_stats(a: str, b: str, px_a: Sequence[float], px_b: Sequence[float],
                  sub_windows: int = 4) -> PairStats:
    """Fit the pair on the supplied trailing window ONLY.

    Callers must pass a window ending at the bar being traded -- this function
    has no way to detect a lookahead violation for you.
    """
    n = min(len(px_a), len(px_b))
    px_a, px_b = list(px_a[-n:]), list(px_b[-n:])
    la = [math.log(p) for p in px_a if p > 0]
    lb = [math.log(p) for p in px_b if p > 0]
    n = min(len(la), len(lb))
    la, lb = la[-n:], lb[-n:]
    if n < 8:
        return PairStats(a, b, n, 0.0, 0.0, 0.0, [], 0.0, 0.0, float("inf"), 0.0, 0.0)

    alpha, beta = ols(lb, la)
    spread = [x - (alpha + beta * y) for x, y in zip(la, lb)]
    mu, sigma = mean(spread), stdev(spread)
    z = (spread[-1] - mu) / sigma if sigma > 0 else 0.0
    hl = half_life(spread)
    adf = adf_tstat(spread)
    corr = correlation(log_returns(px_a), log_returns(px_b))

    # Stability: refit on contiguous sub-windows; count how many stay
    # mean-reverting on their own. A pair that only coheres over the full
    # window is one regime, not a relationship.
    good, chunks = 0, 0
    size = n // sub_windows
    if size >= 12:
        for i in range(sub_windows):
            sa, sb = la[i * size:(i + 1) * size], lb[i * size:(i + 1) * size]
            if len(sa) < 12:
                continue
            chunks += 1
            al2, be2 = ols(sb, sa)
            sp2 = [x - (al2 + be2 * y) for x, y in zip(sa, sb)]
            if math.isfinite(half_life(sp2)) and adf_tstat(sp2) < -1.5:
                good += 1
    stability = (good / chunks) if chunks else 0.0

    return PairStats(a, b, n, beta, alpha, corr, spread, z, sigma, hl, adf, stability)


# --------------------------------------------------------------------------
# screening
# --------------------------------------------------------------------------
@dataclass
class ScreenBars:
    """Admission bars for a pair. Stated as data so pairs.yaml owns them and
    the code cannot quietly relax one."""
    min_n: int = 240          # match pairs.yaml lookback_bars; pinned by test_pairs.py
    min_abs_corr: float = 0.55
    max_half_life: float = 72.0      # bars
    min_half_life: float = 2.0       # below this it is microstructure noise
    max_adf: float = -2.2            # must be at least this negative
    min_stability: float = 0.75
    min_sigma_bps: float = 40.0      # spread vol floor, in bps of log-spread
    beta_range: Tuple[float, float] = (0.25, 4.0)

    def reject_reason(self, s: PairStats) -> Optional[str]:
        if s.n < self.min_n:
            return f"n {s.n} < {self.min_n}"
        if s.sigma <= 0:
            return "degenerate spread (sigma=0)"
        if s.sigma * 10_000 < self.min_sigma_bps:
            return f"spread vol {s.sigma * 10_000:.0f}bps < {self.min_sigma_bps:.0f}bps (no room to pay costs)"
        if abs(s.corr) < self.min_abs_corr:
            return f"|corr| {abs(s.corr):.2f} < {self.min_abs_corr:.2f}"
        if not math.isfinite(s.hl):
            return "spread not mean-reverting (half-life inf)"
        if s.hl > self.max_half_life:
            return f"half-life {s.hl:.0f} > {self.max_half_life:.0f} bars"
        if s.hl < self.min_half_life:
            return f"half-life {s.hl:.1f} < {self.min_half_life:.1f} bars (noise, not signal)"
        if s.adf > self.max_adf:
            return f"adf {s.adf:+.2f} > {self.max_adf:+.2f}"
        if s.stability < self.min_stability:
            return f"stability {s.stability:.2f} < {self.min_stability:.2f} (regime-fit)"
        lo, hi = self.beta_range
        if not (lo <= abs(s.beta) <= hi):
            return f"beta {s.beta:+.2f} outside [{lo}, {hi}]"
        return None

    def accepts(self, s: PairStats) -> bool:
        return self.reject_reason(s) is None


# --------------------------------------------------------------------------
# signal
# --------------------------------------------------------------------------
LONG_SPREAD, SHORT_SPREAD, FLAT = "long_spread", "short_spread", "flat"


@dataclass
class SignalRules:
    entry_z: float = 2.0
    exit_z: float = 0.4
    stop_z: float = 4.0
    max_hold_bars: int = 240
    min_edge_bps: float = 15.0   # expected convergence must clear this


@dataclass
class PairPosition:
    side: str               # LONG_SPREAD (long A / short B) or SHORT_SPREAD
    entry_z: float
    entry_bar: int
    beta: float
    notional_per_leg: float
    entry_px_a: float
    entry_px_b: float


@dataclass
class Decision:
    action: str             # "open" | "close" | "hold" | "none"
    side: str = FLAT
    reason: str = ""
    z: float = 0.0
    edge_bps: float = 0.0


def expected_edge_bps(s: PairStats) -> float:
    """Expected convergence if the spread returns to its mean, in bps of
    per-leg notional. |z|*sigma is the log-spread distance to the mean; in a
    dollar-neutral pair that distance is shared across two legs."""
    return abs(s.z) * s.sigma * 10_000.0 / 2.0


def decide(s: PairStats, rules: SignalRules, pos: Optional[PairPosition],
           bar: int, cost_bps: float) -> Decision:
    """The state machine. `cost_bps` is the all-in round-trip cost per leg."""
    if pos is None:
        if not s.ok_basic:
            return Decision("none", reason="stats unusable")
        edge = expected_edge_bps(s)
        if abs(s.z) < rules.entry_z:
            return Decision("none", z=s.z, edge_bps=edge, reason="inside entry band")
        if abs(s.z) >= rules.stop_z:
            # Already beyond the stop band at entry time: this is a broken
            # relationship or a corporate action, not a rich spread.
            return Decision("none", z=s.z, edge_bps=edge,
                            reason=f"|z| {abs(s.z):.2f} >= stop {rules.stop_z} -- treat as regime break")
        if edge < cost_bps + rules.min_edge_bps:
            return Decision("none", z=s.z, edge_bps=edge,
                            reason=f"edge {edge:.0f}bps < cost {cost_bps:.0f} + margin {rules.min_edge_bps:.0f}")
        # z > 0 means A is rich vs B -> short the spread (short A, long B).
        side = SHORT_SPREAD if s.z > 0 else LONG_SPREAD
        return Decision("open", side=side, z=s.z, edge_bps=edge,
                        reason=f"|z| {abs(s.z):.2f} >= {rules.entry_z}, edge {edge:.0f}bps")

    held = bar - pos.entry_bar
    if abs(s.z) >= rules.stop_z:
        return Decision("close", side=pos.side, z=s.z,
                        reason=f"stop: |z| {abs(s.z):.2f} >= {rules.stop_z}")
    if held >= rules.max_hold_bars:
        return Decision("close", side=pos.side, z=s.z,
                        reason=f"time stop: held {held} >= {rules.max_hold_bars} bars")
    if not math.isfinite(s.hl):
        return Decision("close", side=pos.side, z=s.z,
                        reason="relationship broke (half-life went inf)")
    if abs(s.z) <= rules.exit_z:
        return Decision("close", side=pos.side, z=s.z,
                        reason=f"converged: |z| {abs(s.z):.2f} <= {rules.exit_z}")
    # Sign flip through the mean past the exit band is also a convergence.
    if (pos.side == SHORT_SPREAD and s.z < -rules.exit_z) or \
       (pos.side == LONG_SPREAD and s.z > rules.exit_z):
        return Decision("close", side=pos.side, z=s.z, reason="crossed the mean")
    return Decision("hold", side=pos.side, z=s.z, reason=f"held {held} bars")


# --------------------------------------------------------------------------
# sizing
# --------------------------------------------------------------------------
@dataclass
class SizingRules:
    gross_leverage: float = 2.0      # notional / equity, both legs summed
    max_pairs: int = 4
    max_leg_notional_frac: float = 0.60   # of equity, per leg
    vol_target_bps: float = 0.0      # 0 disables vol targeting


def size_pair(usable_equity: float, s: PairStats, rules: SizingRules,
              n_open: int) -> float:
    """Notional per leg, dollar-neutral.

    Splitting gross leverage across `max_pairs` and then across 2 legs means a
    full book sits at the configured gross, not `max_pairs` times it -- the
    arithmetic error that turns "2x" into "8x" and finds the liquidation price.
    """
    if usable_equity <= 0 or rules.max_pairs <= 0:
        return 0.0
    per_pair_gross = usable_equity * rules.gross_leverage / rules.max_pairs
    notional = per_pair_gross / 2.0
    if rules.vol_target_bps > 0 and s.sigma > 0:
        # Scale down pairs whose spread is wilder than target; never scale up.
        scale = min(1.0, rules.vol_target_bps / (s.sigma * 10_000.0))
        notional *= scale
    return min(notional, usable_equity * rules.max_leg_notional_frac)


def leg_sizes(notional_per_leg: float, px_a: float, px_b: float,
              beta: float) -> Tuple[float, float]:
    """(size_a, size_b) in contracts, beta-weighted and dollar-anchored on A.

    Leg B is scaled by |beta| so the pair is neutral to the *fitted*
    relationship rather than to raw dollars. beta==1 recovers dollar-neutral.
    """
    if px_a <= 0 or px_b <= 0:
        return 0.0, 0.0
    sz_a = notional_per_leg / px_a
    sz_b = (notional_per_leg * abs(beta)) / px_b
    return sz_a, sz_b


# --------------------------------------------------------------------------
# risk
# --------------------------------------------------------------------------
@dataclass
class RiskLimits:
    max_gross_leverage: float = 3.0
    max_margin_ratio: float = 0.50     # used margin / equity
    max_daily_loss_frac: float = 0.05
    max_drawdown_frac: float = 0.15
    min_equity: float = 250.0


@dataclass
class RiskState:
    peak_equity: float = 0.0
    day_start_equity: float = 0.0
    halted: bool = False
    halt_reason: str = ""

    def update(self, equity: float, new_day: bool) -> None:
        if self.peak_equity == 0.0:
            self.peak_equity = equity
            self.day_start_equity = equity
        if new_day:
            self.day_start_equity = equity
        self.peak_equity = max(self.peak_equity, equity)


def check_risk(equity: float, gross_lev: float, margin_ratio: float,
               limits: RiskLimits, state: RiskState) -> Optional[str]:
    """Returns a halt reason, or None if trading may continue.

    A halt blocks NEW risk. Closing an existing pair is always allowed --
    a kill switch that also blocks the exit is not a kill switch.
    """
    if equity < limits.min_equity:
        return f"equity ${equity:,.0f} below floor ${limits.min_equity:,.0f}"
    if gross_lev > limits.max_gross_leverage:
        return f"gross leverage {gross_lev:.2f}x > {limits.max_gross_leverage:.2f}x"
    if margin_ratio > limits.max_margin_ratio:
        return f"margin ratio {margin_ratio:.2f} > {limits.max_margin_ratio:.2f}"
    if state.day_start_equity > 0:
        dd = (state.day_start_equity - equity) / state.day_start_equity
        if dd > limits.max_daily_loss_frac:
            return f"daily loss {dd:.1%} > {limits.max_daily_loss_frac:.1%}"
    if state.peak_equity > 0:
        dd = (state.peak_equity - equity) / state.peak_equity
        if dd > limits.max_drawdown_frac:
            return f"drawdown {dd:.1%} > {limits.max_drawdown_frac:.1%}"
    return None
