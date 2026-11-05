"""Betting selections as events on the final score, priced from the score matrix.

Every selection is a boolean mask over the (home goals, away goals) grid, so any set of
selections on the SAME match can be priced exactly as one event (mask AND mask), which is
what makes same-game parlays correct instead of naively multiplied.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .model import MAX_GOALS

_G = np.arange(MAX_GOALS + 1)
H, A = np.meshgrid(_G, _G, indexing="ij")
T = H + A


@dataclass(frozen=True)
class Selection:
    code: str      # stable id used in odds files, e.g. "O2.5"
    market: str    # family, e.g. "Total goals"
    label: str     # human text; {home}/{away} are filled in
    mask: np.ndarray

    def describe(self, home: str, away: str) -> str:
        return self.label.format(home=home, away=away)


def _sel(code, market, label, mask):
    return Selection(code, market, label, mask)


SELECTIONS: list[Selection] = [
    _sel("H", "1X2", "{home} win", H > A),
    _sel("D", "1X2", "Draw", H == A),
    _sel("A", "1X2", "{away} win", H < A),
    _sel("1X", "Double chance", "{home} or draw", H >= A),
    _sel("X2", "Double chance", "{away} or draw", H <= A),
    _sel("12", "Double chance", "Either team wins", H != A),
    _sel("BTTS_Y", "Both teams to score", "Both teams score", (H > 0) & (A > 0)),
    _sel("BTTS_N", "Both teams to score", "Not both teams score", (H == 0) | (A == 0)),
]
for line in (0.5, 1.5, 2.5, 3.5, 4.5):
    SELECTIONS.append(_sel(f"O{line}", "Total goals", f"Over {line} goals", T > line))
    SELECTIONS.append(_sel(f"U{line}", "Total goals", f"Under {line} goals", T < line))
for line in (0.5, 1.5, 2.5):
    SELECTIONS.append(_sel(f"HO{line}", "Home team goals", f"{{home}} over {line} goals", H > line))
    SELECTIONS.append(_sel(f"AO{line}", "Away team goals", f"{{away}} over {line} goals", A > line))
    SELECTIONS.append(_sel(f"HU{line}", "Home team goals", f"{{home}} under {line} goals", H < line))
    SELECTIONS.append(_sel(f"AU{line}", "Away team goals", f"{{away}} under {line} goals", A < line))
SELECTIONS += [
    _sel("H_WTN", "Win to nil", "{home} win to nil", (H > A) & (A == 0)),
    _sel("A_WTN", "Win to nil", "{away} win to nil", (A > H) & (H == 0)),
]

BY_CODE = {s.code: s for s in SELECTIONS}

# Selections whose outcome partitions the grid, used to strip bookmaker margin.
MARKET_GROUPS = [["H", "D", "A"], ["BTTS_Y", "BTTS_N"]] + \
    [[f"O{x}", f"U{x}"] for x in (0.5, 1.5, 2.5, 3.5, 4.5)] + \
    [[f"HO{x}", f"HU{x}"] for x in (0.5, 1.5, 2.5)] + [[f"AO{x}", f"AU{x}"] for x in (0.5, 1.5, 2.5)]


def prob(matrix: np.ndarray, *codes: str) -> float:
    """Probability that ALL the given selections win in one match."""
    mask = np.ones_like(matrix, dtype=bool)
    for c in codes:
        mask &= BY_CODE[c].mask
    return float(matrix[mask].sum())


def all_probs(matrix: np.ndarray) -> dict[str, float]:
    return {s.code: float(matrix[s.mask].sum()) for s in SELECTIONS}


def most_likely_scores(matrix: np.ndarray, n: int = 3) -> list[tuple[int, int, float]]:
    flat = np.argsort(matrix, axis=None)[::-1][:n]
    return [(int(i // matrix.shape[1]), int(i % matrix.shape[1]), float(matrix.flat[i])) for i in flat]


def implied_probs(odds: dict[str, float]) -> dict[str, float]:
    """Bookmaker odds -> probabilities with the margin removed where a full market is quoted.

    Selections without their complement quoted get 1/odds shrunk by a typical 5% margin.
    """
    out = {}
    for group in MARKET_GROUPS:
        if all(c in odds for c in group):
            raw = {c: 1 / odds[c] for c in group}
            z = sum(raw.values())
            out.update({c: v / z for c, v in raw.items()})
    for c, o in odds.items():
        out.setdefault(c, min(1.0, (1 / o) / 1.05))
    return out
