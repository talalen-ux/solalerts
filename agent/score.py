#!/usr/bin/env python3
"""Deterministic profit scorer for DRBT backtest summaries.

A backtest summary only gives P(peak multiple >= k) for k in THRESHOLDS, so
profit is MODELLED, never observed:
  * each alert is bought at the alert price, stake = 1
  * a ladder of take-profit tranches sells at fixed multiples
  * tranches not reached exit at breakeven once the first target has hit
    (stop moved to cost), else at STOP (a loss; deliberately harsh to cover rugs)
  * entry and exit friction (free-tier 15s delay, fees, creator tax, slippage)
  * every probability is replaced by its Wilson lower bound for the verdict
Because EV is increasing in every P(X>=k), using lower bounds is a valid
conservative bound. Nothing here can prove future profit; it only refuses to
promote strategies that cannot clear the bar under pessimistic assumptions.
"""
import json, math, sys

THRESHOLDS = [2, 3, 5, 10, 20, 50, 100]

# (target multiple, weight) tranches; weights sum to 1
POLICIES = {
    "ladder_3_10": [(3, 0.5), (10, 0.5)],
    "ladder_2_5_20": [(2, 0.4), (5, 0.3), (20, 0.3)],
    "moon_10_50": [(10, 0.5), (50, 0.5)],
    "scalp_2": [(2, 1.0)],
}

DEFAULT_COST = {"f_in": 0.10, "f_out": 0.08, "stop": 0.40, "miss_exit": 0.50}

# Probability that a tranche really FILLS when the peak multiple reaches its
# target. Peaks are often one-block wicks; the bigger the target the likelier the
# peak was untradeable. A missed fill exits at miss_exit (price came back down).
FILL = {2: 0.92, 3: 0.88, 5: 0.82, 10: 0.70, 20: 0.55, 50: 0.40, 100: 0.30}


def wilson_lcb(k, n, z=1.645):
    """One-sided ~95% lower confidence bound for a binomial proportion."""
    if n <= 0:
        return 0.0
    p = k / n
    d = 1 + z * z / n
    centre = p + z * z / (2 * n)
    adj = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - adj) / d)


def parse_summary(raw):
    """Accept a raw MCP backtest result (reached list) or a compact dict."""
    if "n" in raw and "reached" in raw and isinstance(raw["reached"], dict):
        n = int(raw["n"])
        reached = {int(k): int(v) for k, v in raw["reached"].items()}
    else:
        n = int(raw.get("scored", raw.get("matched", 0)))
        reached = {int(r["at_least_x"]): int(r["tokens"]) for r in raw["reached"]}
    for t in THRESHOLDS:
        reached.setdefault(t, 0)
    # enforce monotone non-increasing counts
    last = n
    for t in THRESHOLDS:
        reached[t] = min(reached[t], last)
        last = reached[t]
    return {"n": n, "reached": {t: reached[t] for t in THRESHOLDS}}


def subtract(long_s, recent_s):
    """Older part of a window = long minus recent (recent window is a subset)."""
    n = long_s["n"] - recent_s["n"]
    reached = {t: max(0, long_s["reached"][t] - recent_s["reached"][t]) for t in THRESHOLDS}
    return parse_summary({"n": max(0, n), "reached": reached})


def _ev(probs, policy, cost):
    """probs: {k: P(X>=k)} including every tranche target. Returns EV-1 per stake."""
    f_in, f_out, stop = cost["f_in"], cost["f_out"], cost["stop"]
    t1 = policy[0][0]
    p1 = probs[t1]

    def net(m):  # net proceeds per unit stake for a gross multiple m
        return m * (1 - f_out) / (1 + f_in)

    miss = cost["miss_exit"]
    ev = 0.0
    for t, w in policy:
        pt = probs[t]
        fill = FILL[t]
        reached_val = fill * net(t) + (1 - fill) * net(miss)
        ev += w * (pt * reached_val + (p1 - pt) * net(1.0) + (1 - p1) * net(stop))
    return ev - 1.0


def evaluate(summary, cost=None):
    cost = {**DEFAULT_COST, **(cost or {})}
    n = summary["n"]
    out = {"n": n, "policies": {}}
    if n == 0:
        out["best"] = None
        return out
    pt = {t: summary["reached"][t] / n for t in THRESHOLDS}
    lcb = {t: wilson_lcb(summary["reached"][t], n) for t in THRESHOLDS}
    for name, pol in POLICIES.items():
        out["policies"][name] = {
            "ev": round(_ev(pt, pol, cost), 4),
            "ev_lcb": round(_ev(lcb, pol, cost), 4),
        }
    best = max(out["policies"], key=lambda k: out["policies"][k]["ev_lcb"])
    out["best"] = best
    out["ev"] = out["policies"][best]["ev"]
    out["ev_lcb"] = out["policies"][best]["ev_lcb"]
    out["hit2"] = round(pt[2], 4)
    out["hit10"] = round(pt[10], 4)
    return out


GATES = {
    "min_n_long": 30,        # tokens in the long window
    "min_n_half": 10,        # tokens in each time half
    "min_ev_lcb": 0.0,       # conservative EV must be positive
    "min_ev_half": 0.0,      # point EV positive in BOTH halves
    "max_alerts_per_day": 150,
    "margin_vs_champion": 0.05,  # challenger EV_lcb must beat champion by this
}


def verdict(long_s, recent_s, long_hours, champion_ev_lcb=None, cost=None, gates=None):
    g = {**GATES, **(gates or {})}
    older_s = subtract(long_s, recent_s)
    lo, re_, ol = evaluate(long_s, cost), evaluate(recent_s, cost), evaluate(older_s, cost)
    best = lo.get("best")
    reasons = []
    if best is None:
        reasons.append("no tokens")
    else:
        if long_s["n"] < g["min_n_long"]:
            reasons.append(f"n_long {long_s['n']} < {g['min_n_long']}")
        if recent_s["n"] < g["min_n_half"] or older_s["n"] < g["min_n_half"]:
            reasons.append(f"half sizes {older_s['n']}/{recent_s['n']} < {g['min_n_half']}")
        if lo["ev_lcb"] <= g["min_ev_lcb"]:
            reasons.append(f"ev_lcb {lo['ev_lcb']} <= {g['min_ev_lcb']}")
        for label, ev in (("older", ol), ("recent", re_)):
            if ev.get("best") is not None and ev["policies"][best]["ev"] <= g["min_ev_half"]:
                reasons.append(f"{label} half ev {ev['policies'][best]['ev']} <= {g['min_ev_half']} (policy {best})")
        per_day = long_s["n"] / (long_hours / 24.0)
        if per_day > g["max_alerts_per_day"]:
            reasons.append(f"alerts/day {per_day:.0f} > {g['max_alerts_per_day']}")
        if champion_ev_lcb is not None and lo["ev_lcb"] < champion_ev_lcb + g["margin_vs_champion"]:
            reasons.append(f"ev_lcb {lo['ev_lcb']} < champion {champion_ev_lcb} + {g['margin_vs_champion']}")
    return {
        "pass": not reasons,
        "reasons": reasons,
        "long": lo, "recent": re_, "older": ol,
        "alerts_per_day": round(long_s["n"] / (long_hours / 24.0), 1),
    }


def main(argv):
    if len(argv) < 3:
        print("usage: score.py LONG.json RECENT.json LONG_HOURS [CHAMPION_EV_LCB]")
        return 2
    long_s = parse_summary(json.load(open(argv[0 + 1])))
    recent_s = parse_summary(json.load(open(argv[1 + 1])))
    champ = float(argv[4]) if len(argv) > 4 else None
    print(json.dumps(verdict(long_s, recent_s, float(argv[3]), champ), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
