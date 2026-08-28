#!/usr/bin/env python3
"""CLI for the Ethena/Hyperliquid equity pair book.

    python3 lab/pairs_run.py markets  [--dex NAME]
    python3 lab/pairs_run.py scan     [--dex NAME] [--days 60] [--interval 1h]
    python3 lab/pairs_run.py backtest --pair AAPL,MSFT [--dex NAME] [--days 90]
    python3 lab/pairs_run.py signal   --pair AAPL,MSFT [--dex NAME]
    python3 lab/pairs_run.py carry    [--leverage 2.0]
    python3 lab/pairs_run.py trade    --pair AAPL,MSFT [--live]

`trade` is DRY-RUN unless BOTH --live is passed AND HL_ALLOW_LIVE=1 is set in
the environment. Two switches, deliberately.

All market data comes from the public Hyperliquid info endpoint; nothing here
needs an API key except `trade --live`.
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ethena
import hl
from pairs import (LONG_SPREAD, ScreenBars, SignalRules, SizingRules,
                   compute_stats, decide, expected_edge_bps, leg_sizes, size_pair)
from pairs_backtest import Costs, Series, backtest_pair

DEFAULT_FALLBACK_APY = 0.08


# --------------------------------------------------------------------------
def fetch_series(md: hl.MarketData, m: hl.Market, days: float, interval: str,
                 with_funding: bool = True) -> Series:
    start, end = hl.days_ago_ms(days), hl.now_ms()
    closes = md.closes(m.name, interval, start, end)
    ts = [t for t, _ in closes]
    px = [p for _, p in closes]
    funding: List[float] = []
    if with_funding and ts:
        fh = dict(md.hourly_funding(m.name, start, end))
        # Snap each bar to the funding stamp at or before it.
        keys = sorted(fh)
        j, cur = 0, 0.0
        for t in ts:
            while j < len(keys) and keys[j] <= t:
                cur = fh[keys[j]]
                j += 1
            funding.append(cur)
    return Series(m.qualified, ts, px, funding)


def resolve_universe(dexs: List[str]) -> hl.Universe:
    return hl.Universe(dexs=dexs or [""])


def parse_pair(s: str) -> Tuple[str, str]:
    parts = [p.strip() for p in s.split(",")]
    if len(parts) != 2 or not all(parts):
        raise SystemExit(f"--pair expects A,B (got {s!r})")
    return parts[0], parts[1]


def get_curve(args) -> Tuple[ethena.YieldCurve, bool]:
    if getattr(args, "apy", None) is not None:
        return ethena.YieldCurve.constant(args.apy, haircut=args.haircut), False
    return ethena.YieldCurve.live_or(DEFAULT_FALLBACK_APY, haircut=args.haircut)


# --------------------------------------------------------------------------
def cmd_markets(args) -> int:
    u = resolve_universe(args.dex)
    print(f"{'market':<28} {'asset':>8} {'szDec':>6} {'maxLev':>7}  dex")
    for name in sorted(u.markets):
        m = u.markets[name]
        print(f"{m.qualified:<28} {m.asset:>8} {m.sz_decimals:>6} {m.max_leverage:>7}  {m.dex or '(core)'}")
    print(f"\n{len(u.markets)} markets across dexs {[d or '(core)' for d in (args.dex or [''])]}")
    return 0


def cmd_scan(args) -> int:
    """Screen every candidate pair in the loaded universe."""
    u = resolve_universe(args.dex)
    md = hl.MarketData(universe=u)
    names = args.symbols or sorted(u.markets)
    if len(names) > args.max_symbols:
        print(f"universe has {len(names)} markets; capping at {args.max_symbols} "
              f"(use --symbols to choose). ", file=sys.stderr)
        names = names[:args.max_symbols]

    print(f"loading {len(names)} series ({args.days}d @ {args.interval}) ...", file=sys.stderr)
    series: Dict[str, Series] = {}
    for n in names:
        try:
            m = u.get(n)
            s = fetch_series(md, m, args.days, args.interval, with_funding=False)
            if len(s.close) >= args.lookback:
                series[m.qualified] = s
        except Exception as e:
            print(f"  skip {n}: {e}", file=sys.stderr)

    bars = ScreenBars(min_n=args.lookback)
    costs = Costs(taker_fee_bps=args.fee_bps, slippage_bps=args.slip_bps)
    rows = []
    for a, b in itertools.combinations(sorted(series), 2):
        sa, sb = series[a], series[b]
        idx = {t: i for i, t in enumerate(sb.ts)}
        pa = [sa.close[i] for i, t in enumerate(sa.ts) if t in idx]
        pb = [sb.close[idx[t]] for t in sa.ts if t in idx]
        if len(pa) < args.lookback:
            continue
        st = compute_stats(sa.name, sb.name, pa[-args.lookback:], pb[-args.lookback:])
        why = bars.reject_reason(st)
        edge = expected_edge_bps(st)
        rows.append((st, why, edge, edge - costs.pair_round_trip_bps))

    passing = [r for r in rows if r[1] is None]
    passing.sort(key=lambda r: (-abs(r[0].z), r[0].hl))
    print(f"\n=== screened {len(rows)} pairs, {len(passing)} pass the bars ===")
    for st, _, edge, net in passing[:args.top]:
        flag = "  <-- TRADEABLE NOW" if abs(st.z) >= args.entry_z and net > 0 else ""
        print(f"  {st.summary()}  edge {edge:.0f}bps net {net:+.0f}bps{flag}")
    if not passing:
        print("  nothing passes -- the bars are doing their job; do not relax them silently")
    if args.show_rejects:
        print("\n--- rejected ---")
        for st, why, _, _ in sorted(rows, key=lambda r: r[0].a)[:args.top]:
            if why:
                print(f"  {st.a}/{st.b}: {why}")
    return 0


def cmd_backtest(args) -> int:
    a, b = parse_pair(args.pair)
    u = resolve_universe(args.dex)
    md = hl.MarketData(universe=u)
    ma, mb = u.get(a), u.get(b)
    sa = fetch_series(md, ma, args.days, args.interval)
    sb = fetch_series(md, mb, args.days, args.interval)
    curve, live = get_curve(args)
    if not live and args.apy is None:
        print(f"note: sUSDe feed unreachable; assuming {DEFAULT_FALLBACK_APY:.1%} APY "
              f"(override with --apy)", file=sys.stderr)

    res = backtest_pair(
        sa, sb,
        equity=args.equity, lookback=args.lookback, curve=curve,
        costs=Costs(taker_fee_bps=args.fee_bps, slippage_bps=args.slip_bps),
        rules=SignalRules(entry_z=args.entry_z, exit_z=args.exit_z,
                          stop_z=args.stop_z, max_hold_bars=args.max_hold),
        sizing=SizingRules(gross_leverage=args.leverage, max_pairs=args.max_pairs),
        bars_screen=ScreenBars(min_n=args.lookback),
        staked_frac=args.staked_frac,
        bars_per_day=args.bars_per_day,
    )
    print(res.report())
    if args.trades:
        print("\n  bar   side          z_in   z_out  hold   spread   fund    fees     net")
        for t in res.trades:
            print(f"  {t.open_bar:>5} {t.side:<12} {t.entry_z:+5.2f}  {t.exit_z:+5.2f}  "
                  f"{t.bars_held:>4}  {t.spread_pnl:+7.0f} {t.funding_pnl:+6.0f} "
                  f"{-t.fees:+7.0f} {t.net_pnl:+7.0f}   {t.reason}")
    return 0


def cmd_signal(args) -> int:
    a, b = parse_pair(args.pair)
    u = resolve_universe(args.dex)
    md = hl.MarketData(universe=u)
    ma, mb = u.get(a), u.get(b)
    sa = fetch_series(md, ma, args.days, args.interval, with_funding=False)
    sb = fetch_series(md, mb, args.days, args.interval, with_funding=False)

    idx = {t: i for i, t in enumerate(sb.ts)}
    pa = [sa.close[i] for i, t in enumerate(sa.ts) if t in idx]
    pb = [sb.close[idx[t]] for t in sa.ts if t in idx]
    if len(pa) < args.lookback:
        print(f"only {len(pa)} aligned bars, need {args.lookback}")
        return 1

    st = compute_stats(ma.qualified, mb.qualified, pa[-args.lookback:], pb[-args.lookback:])
    costs = Costs(taker_fee_bps=args.fee_bps, slippage_bps=args.slip_bps)
    bars = ScreenBars(min_n=args.lookback)
    rules = SignalRules(entry_z=args.entry_z, exit_z=args.exit_z, stop_z=args.stop_z)

    print(st.summary())
    why = bars.reject_reason(st)
    print(f"  screen: {'PASS' if why is None else 'REJECT -- ' + why}")
    d = decide(st, rules, None, 0, costs.pair_round_trip_bps)
    print(f"  signal: {d.action.upper()} {d.side if d.action == 'open' else ''} -- {d.reason}")
    print(f"  edge {d.edge_bps:.0f}bps vs round-trip cost {costs.pair_round_trip_bps:.0f}bps")

    curve, live = get_curve(args)
    coll = ethena.Collateral(equity=args.equity, staked_frac=args.staked_frac)
    print(f"  {ethena.describe(curve, coll, hl.now_ms())}"
          f"{'' if live else '  [feed unreachable -- assumed]'}")
    return 0


def cmd_carry(args) -> int:
    """The leverage/carry tradeoff, printed before you pick leverage."""
    curve, live = get_curve(args)
    ts = hl.now_ms()
    coll = ethena.Collateral(equity=args.equity, staked_frac=args.staked_frac)
    print(ethena.describe(curve, coll, ts) + ("" if live else "  [assumed]"))
    fl = args.long_funding / 100.0 / 24.0 / 365.0 if args.funding_is_apr else args.long_funding
    fs = args.short_funding / 100.0 / 24.0 / 365.0 if args.funding_is_apr else args.short_funding
    print(f"\n{'gross lev':>10} {'net carry':>14} {'breakeven move':>16}")
    for lev in (1.0, 1.5, 2.0, 3.0, 4.0, 5.0):
        carry = ethena.net_carry_bps_per_day(curve, ts, fl, fs, lev, args.staked_frac)
        be = ethena.breakeven_spread_move_bps(
            curve, ts, args.hold_days, args.fee_bps, args.slip_bps, lev, fl, fs,
            args.staked_frac)
        mark = "  <-- configured" if abs(lev - args.leverage) < 1e-9 else ""
        print(f"{lev:>9.1f}x {carry:>+11.2f}bps/d {be:>+13.1f}bps{mark}")
    print("\nyield accrues on equity, funding on notional: carry per unit of "
          "notional falls as leverage rises.")
    return 0


def cmd_trade(args) -> int:
    a, b = parse_pair(args.pair)
    u = resolve_universe(args.dex)
    md = hl.MarketData(universe=u)
    ma, mb = u.get(a), u.get(b)

    sa = fetch_series(md, ma, args.days, args.interval, with_funding=False)
    sb = fetch_series(md, mb, args.days, args.interval, with_funding=False)
    idx = {t: i for i, t in enumerate(sb.ts)}
    pa = [sa.close[i] for i, t in enumerate(sa.ts) if t in idx]
    pb = [sb.close[idx[t]] for t in sa.ts if t in idx]
    if len(pa) < args.lookback:
        print(f"only {len(pa)} aligned bars, need {args.lookback} -- refusing to trade")
        return 1

    st = compute_stats(ma.qualified, mb.qualified, pa[-args.lookback:], pb[-args.lookback:])
    costs = Costs(taker_fee_bps=args.fee_bps, slippage_bps=args.slip_bps)
    bars = ScreenBars(min_n=args.lookback)
    rules = SignalRules(entry_z=args.entry_z, exit_z=args.exit_z, stop_z=args.stop_z)

    print(st.summary())
    why = bars.reject_reason(st)
    if why:
        print(f"  screen REJECT -- {why}. No order.")
        return 0
    d = decide(st, rules, None, 0, costs.pair_round_trip_bps)
    if d.action != "open":
        print(f"  no entry: {d.reason}")
        return 0

    # Size against live collateral if an address is available, else the flag.
    equity = args.equity
    addr = args.address or os.environ.get(hl.Executor.ADDR_ENV)
    if addr:
        try:
            acct = hl.Account(addr)
            st_dex = ma.dex
            equity = acct.state(dex=st_dex).account_value or equity
            print(f"  live account value on dex {st_dex or '(core)'}: ${equity:,.2f}")
        except Exception as e:
            print(f"  could not read account ({e}); sizing off --equity", file=sys.stderr)

    coll = ethena.Collateral(equity=equity, staked_frac=args.staked_frac)
    sizing = SizingRules(gross_leverage=args.leverage, max_pairs=args.max_pairs)
    notional = size_pair(coll.usable, st, sizing, n_open=0)

    mids_a = md.all_mids(ma.dex)
    mids_b = mids_a if mb.dex == ma.dex else md.all_mids(mb.dex)
    px_a, px_b = float(mids_a[ma.name]), float(mids_b[mb.name])
    sz_a, sz_b = leg_sizes(notional, px_a, px_b, st.beta)

    long_a = (d.side == LONG_SPREAD)
    slip = args.slip_bps / 10_000.0
    intents = [
        hl.OrderIntent(ma, long_a, sz_a, hl.slippage_px(px_a, long_a, slip, ma),
                       note=f"leg A {d.side}"),
        hl.OrderIntent(mb, not long_a, sz_b, hl.slippage_px(px_b, not long_a, slip, mb),
                       note=f"leg B beta={st.beta:+.3f}"),
    ]
    print(f"  {d.side}: ${notional:,.0f}/leg at {args.leverage:g}x gross across "
          f"{args.max_pairs} pair slots -- {d.reason}")

    ex = hl.Executor(live=args.live, account_address=addr)
    if not args.live:
        print("  (dry-run -- pass --live AND set HL_ALLOW_LIVE=1 to send)")
    res = ex.send(intents)
    for r in res:
        print(f"  -> {json.dumps(r) if not isinstance(r, str) else r}")
    return 0


# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, needs_pair=False):
        sp.add_argument("--dex", action="append", default=None,
                        help='perp dex to load; repeatable. "" = core. HIP-3 equity '
                             'markets live on a builder dex, so name it.')
        sp.add_argument("--days", type=float, default=60.0)
        sp.add_argument("--interval", default="1h")
        sp.add_argument("--lookback", type=int, default=240)
        sp.add_argument("--equity", type=float, default=10_000.0)
        sp.add_argument("--leverage", type=float, default=2.0)
        sp.add_argument("--max-pairs", type=int, default=4, dest="max_pairs")
        sp.add_argument("--staked-frac", type=float, default=0.80, dest="staked_frac")
        sp.add_argument("--haircut", type=float, default=0.25,
                        help="discount applied to the quoted sUSDe APY")
        sp.add_argument("--apy", type=float, default=None,
                        help="override sUSDe APY as a fraction, e.g. 0.08")
        sp.add_argument("--fee-bps", type=float, default=4.5, dest="fee_bps")
        sp.add_argument("--slip-bps", type=float, default=3.0, dest="slip_bps")
        sp.add_argument("--entry-z", type=float, default=2.0, dest="entry_z")
        sp.add_argument("--exit-z", type=float, default=0.4, dest="exit_z")
        sp.add_argument("--stop-z", type=float, default=4.0, dest="stop_z")
        if needs_pair:
            sp.add_argument("--pair", required=True, help="A,B")

    sp = sub.add_parser("markets", help="list loaded markets and wire asset ids")
    sp.add_argument("--dex", action="append", default=None)
    sp.set_defaults(func=cmd_markets)

    sp = sub.add_parser("scan", help="screen all candidate pairs")
    common(sp)
    sp.add_argument("--symbols", action="append", default=None)
    sp.add_argument("--top", type=int, default=25)
    sp.add_argument("--max-symbols", type=int, default=40, dest="max_symbols")
    sp.add_argument("--show-rejects", action="store_true", dest="show_rejects")
    sp.set_defaults(func=cmd_scan)

    sp = sub.add_parser("backtest", help="walk-forward backtest one pair")
    common(sp, needs_pair=True)
    sp.add_argument("--max-hold", type=int, default=240, dest="max_hold")
    sp.add_argument("--bars-per-day", type=float, default=24.0, dest="bars_per_day")
    sp.add_argument("--trades", action="store_true", help="print the trade blotter")
    sp.set_defaults(func=cmd_backtest)

    sp = sub.add_parser("signal", help="current signal for one pair")
    common(sp, needs_pair=True)
    sp.set_defaults(func=cmd_signal)

    sp = sub.add_parser("carry", help="net carry vs leverage table")
    common(sp)
    sp.add_argument("--long-funding", type=float, default=0.0, dest="long_funding")
    sp.add_argument("--short-funding", type=float, default=0.0, dest="short_funding")
    sp.add_argument("--funding-is-apr", action="store_true", dest="funding_is_apr",
                    help="interpret funding args as annualised percent")
    sp.add_argument("--hold-days", type=float, default=3.0, dest="hold_days")
    sp.set_defaults(func=cmd_carry)

    sp = sub.add_parser("trade", help="emit orders for one pair (dry-run by default)")
    common(sp, needs_pair=True)
    sp.add_argument("--live", action="store_true",
                    help=f"send real orders; also requires {hl.Executor.LIVE_ENV}=1")
    sp.add_argument("--address", default=None, help="account address to size against")
    sp.set_defaults(func=cmd_trade)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except hl.HLError as e:
        print(f"hyperliquid: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
