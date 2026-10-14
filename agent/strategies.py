"""Strategy families, parameter grids, additive predicates and the safety lint."""
import hashlib, re

FAMILIES = {
    "hooked_verified": {
        "windows": {"long": 336, "recent": 168},
        "template": ("launchpad = 'uniswap_v4' AND hooked AND round_trip_back >= {rtb} AND buyers >= {buyers} "
                     "AND buy_volume_usd > {ratio} * sell_volume_usd AND top_maker_pct < {top} "
                     "AND mc > {mc_min} AND mc < {mc_max}"),
        "grid": {"rtb": [0.85, 0.9, 0.95], "buyers": [5, 8, 12, 20], "ratio": [1.5, 2, 3, 5],
                 "top": [50, 60, 70], "mc_min": [5000, 8000, 15000], "mc_max": [100000, 200000, 400000]},
    },
    "plain_v4": {
        "windows": {"long": 168, "recent": 72},
        "template": ("launchpad = 'uniswap_v4' AND NOT hooked AND buyers >= {buyers} "
                     "AND buy_volume_usd > {ratio} * sell_volume_usd AND top_maker_pct < {top} "
                     "AND mc > {mc_min} AND mc < {mc_max}"),
        "grid": {"buyers": [15, 20, 25, 35, 50], "ratio": [3, 4, 5, 6, 8], "top": [30, 40, 50],
                 "mc_min": [10000, 15000, 20000], "mc_max": [30000, 45000, 60000, 100000]},
    },
}

# Optional extra predicates, all NULL-guarded. The bandit learns which ones help.
PREDICATES = {
    "socials": "socials_count >= 1",
    "unique_symbol": "symbol_reuse <= 3",
    "alive": "idle_blocks < 1200",
    "no_sweep": "(swept_pct IS NULL OR swept_pct < 15)",
    "no_untracked": "(untracked_sell_pct IS NULL OR untracked_sell_pct < 10)",
    "held_low": "(held_pct IS NULL OR held_pct < 60)",
    "low_tax": "(creator_tax_bps IS NULL OR creator_tax_bps <= 300)",
    "clean_dev": "(dev_funder_devs IS NULL OR dev_funder_devs = 0)",
}

# Columns that are NULL in backtests (a condition using them matches nothing) or
# that leak the future. A condition containing any of these is rejected.
BANNED_COLUMNS = ["router_count", "fee_recipient_changes", "ath_x", "now_x", "ath_mc", "ath_block"]


def render(family, params, preds=()):
    cond = FAMILIES[family]["template"].format(**params)
    for p in preds:
        cond += " AND " + PREDICATES[p]
    return cond


def cond_hash(cond):
    norm = re.sub(r"\s+", " ", cond.strip().lower())
    return hashlib.sha1(norm.encode()).hexdigest()[:12]


def lint(cond):
    """Return a list of violations; empty means the condition may be tested/deployed."""
    v = []
    c = cond.lower()
    if len(cond) > 1500:
        v.append("condition longer than 1500 chars")
    if cond.count("(") != cond.count(")"):
        v.append("unbalanced parentheses")
    if "launchpad" not in c:
        v.append("must pin launchpad (a clause-free filter matches every venue)")
    if "'uniswap_v4'" in c:
        ok_hook = "not hooked" in c
        m = re.search(r"round_trip_back\s*>=\s*([0-9.]+)", c)
        ok_rtb = bool(m) and float(m.group(1)) >= 0.85 and " hooked" in c
        if not (ok_hook or ok_rtb):
            v.append("uniswap_v4 needs 'NOT hooked' or 'hooked AND round_trip_back >= 0.85+' (unsellable honeypots)")
    for col in BANNED_COLUMNS:
        if re.search(r"\b" + col + r"\b", c):
            v.append(f"banned column {col} (NULL in backtests or leaks the future)")
    m = re.search(r"buyers\s*>=?\s*(\d+)", c)
    if not m or int(m.group(1)) < 5:
        v.append("needs buyers >= 5 or more")
    if not re.search(r"\bmc\s*>", c) or not re.search(r"\bmc\s*<", c):
        v.append("needs both a lower and an upper mc bound")
    return v
