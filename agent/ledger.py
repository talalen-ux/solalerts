#!/usr/bin/env python3
"""Memory + decisions for the strategy agent.

  init                       seed memory.json (idempotent)
  eval  RUN.json             score candidates, update learning, print deploy advice
  baseline SLOT LONG.json RECENT.json LONG_HOURS   refresh a champion's baseline
  watch SLOT RECENT.json     drift check for a live champion (2 alarms => rollback)
  adopt RUN.json ID          record that candidate ID was deployed to its slot
  note TEXT                  append a lesson to memory facts
  status                     one-screen summary
"""
import json, sys, time
import memory_io
from score import parse_summary, verdict, evaluate
from strategies import cond_hash, lint

NOW = lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
ABS_MARGIN, REL_MARGIN = 0.05, 0.10


def seed():
    return {
        "version": 1, "created": NOW(), "cycles": [], "queue": [], "tested": {}, "arms": {},
        "slots": {
            "154": {"family": "hooked_verified", "preds": [],
                    "params": {"rtb": 0.9, "buyers": 8, "ratio": 2, "top": 60, "mc_min": 8000, "mc_max": 200000},
                    "condition": ("launchpad = 'uniswap_v4' AND hooked AND round_trip_back >= 0.9 AND buyers >= 8 AND "
                                  "buy_volume_usd > 2 * sell_volume_usd AND top_maker_pct < 60 AND mc > 8000 AND mc < 200000"),
                    "baseline": {"hours": 336, "n": 48, "ev_lcb": 5.683, "source": "2026-10-13 backtest"},
                    "failures": 0, "alarms": 0},
            "155": {"family": "plain_v4", "preds": [],
                    "params": {"buyers": 25, "ratio": 5, "top": 40, "mc_min": 15000, "mc_max": 45000},
                    "condition": ("launchpad = 'uniswap_v4' AND NOT hooked AND buyers >= 25 AND buy_volume_usd > 5 * "
                                  "sell_volume_usd AND top_maker_pct < 40 AND mc > 15000 AND mc < 45000"),
                    "baseline": {"hours": 168, "n": 396, "ev_lcb": 0.194, "source": "2026-10-13 backtest"},
                    "failures": 0, "alarms": 0},
            "152": {"family": "pons_avalanche", "preds": [], "params": {},
                    "condition": "see alerts.yaml (AVALANCHE + cheap-graduate bundle); not mutated by the agent",
                    "baseline": {"hours": 168, "n": 662, "ev_lcb": -0.336, "source": "2026-10-13 backtest"},
                    "failures": 1, "alarms": 0},
        },
        "facts": [
            "Backtest multiples are PEAKS from the alert price, never exits; profit is modelled in score.py.",
            "uniswap_v4 hooked pools with round_trip_back < 0.9 or NULL are unsellable/unchecked: they carried 17 of 46 50x+ and 6 of 17 100x+ of old TEMPEST (SFFINU 504x -> 0, LUCKYKEY, PDCAP). Never alert on them.",
            "Named launchpads (doppler/clanker/cashcat/pair/launchhook/cook/klik) fire ~12 tokens/week: not worth a slot.",
            "router_count, fee_recipient_changes are NULL in backtests (0 matches); ath_x/now_x leak the future: banned.",
            "Entry-time safety columns (held_pct, swept_pct, untracked_sell_pct) gave no lift on plain pools; fresh_pct band gave none on pons.",
            "Tightening entry knobs trades tail for hit rate (plain tight: 2x+ 73% but 50x+ 3 vs wide 11).",
            "Hooked launches seed ~ $50k mc; entries cluster $38-59k. Free tier alerts arrive 15s late.",
            "Momentum tiers (mc 40-100k with buyers>=40) match 0 tokens: strong runners are caught at $15-60k with 15-40 buyers.",
            "A backtest window includes re-entry effects; use time-split (older vs recent) to check stability.",
        ],
    }


def required_ev(champ_ev):
    return champ_ev + max(ABS_MARGIN, REL_MARGIN * abs(champ_ev))


def cmd_init(_):
    if memory_io.load() is not None:
        print("memory exists"); return
    memory_io.save(seed()); print("seeded")


def cmd_eval(a):
    mem = memory_io.load()
    run = json.load(open(a[0]))
    rows, passing = [], []
    for r in run["results"]:
        lh = float(r.get("long_hours", run.get("long_hours", 168)))
        slot = str(r["slot"])
        champ = mem["slots"][slot]["baseline"]
        long_s, recent_s = parse_summary(r["long"]), parse_summary(r["recent"])
        viol = lint(r["condition"])
        need = required_ev(champ["ev_lcb"]) if champ.get("hours") == lh else None
        v = verdict(long_s, recent_s, lh, champion_ev_lcb=need, gates={"margin_vs_champion": 0.0})
        if viol:
            v["pass"] = False; v["reasons"] = ["LINT: " + x for x in viol] + v["reasons"]
        if champ.get("hours") != lh:
            v["reasons"].append(f"champion baseline window {champ.get('hours')}h != {lh}h: refresh baseline first")
            v["pass"] = False
        delta = v["long"].get("ev_lcb", 0) - champ["ev_lcb"] if v["long"].get("best") else 0
        arm = r.get("arm", "queue")
        s = mem["arms"].setdefault(arm, {"tests": 0, "wins": 0, "sum_delta": 0.0})
        s["tests"] += 1; s["wins"] += 1 if v["pass"] else 0; s["sum_delta"] = round(s["sum_delta"] + delta, 4)
        h = r.get("hash") or cond_hash(r["condition"])
        mem["tested"][h] = {"date": NOW(), "slot": slot, "arm": arm, "n": long_s["n"],
                            "ev_lcb": v["long"].get("ev_lcb"), "pass": v["pass"], "cond": r["condition"][:300]}
        rows.append((r["id"], slot, arm, long_s["n"], v["long"].get("ev_lcb"), round(delta, 3), v["pass"], v["reasons"][:2]))
        if v["pass"]:
            passing.append((v["long"]["ev_lcb"], r, v))
    mem["queue"] = [q for q in mem.get("queue", []) if cond_hash(q["condition"]) not in mem["tested"]]
    mem["cycles"].append({"at": NOW(), "tested": len(rows), "passed": len(passing), "run": a[0]})
    memory_io.save(mem)
    print(f"{'id':16s} slot arm{' ' * 30} n   ev_lcb  delta pass")
    for row in rows:
        print(f"{row[0]:16s} {row[1]} {row[2]:34s} {row[3]:4d} {row[4]!s:7s} {row[5]:+.3f} {row[6]}  {row[7]}")
    if passing:
        passing.sort(key=lambda x: -x[0])
        ev, r, v = passing[0]
        print(f"\nDEPLOY ADVICE (max 1 per cycle): slot {r['slot']} <- {r['id']}  ev_lcb {ev}")
        print(r["condition"])
    else:
        print("\nNO DEPLOYMENT: no candidate cleared every gate")


def cmd_baseline(a):
    mem = memory_io.load(); slot = a[0]
    long_s, recent_s = parse_summary(json.load(open(a[1]))), parse_summary(json.load(open(a[2])))
    lh = float(a[3])
    v = verdict(long_s, recent_s, lh)
    ch = mem["slots"][slot]
    ch["baseline"] = {"hours": lh, "n": long_s["n"], "ev_lcb": v["long"].get("ev_lcb", 0), "source": NOW()}
    # absolute-gate failure counter => demotion after 2 consecutive failures
    ch["failures"] = ch.get("failures", 0) + 1 if not v["pass"] else 0
    memory_io.save(mem)
    print(json.dumps({"slot": slot, "pass": v["pass"], "reasons": v["reasons"], "ev_lcb": ch["baseline"]["ev_lcb"],
                      "failures": ch["failures"],
                      "action": "DISABLE or REPLACE (2 consecutive failures)" if ch["failures"] >= 2 else "keep"}, indent=1))


def cmd_watch(a):
    mem = memory_io.load(); slot = a[0]
    rec = parse_summary(json.load(open(a[1])))
    e = evaluate(rec); ch = mem["slots"][slot]
    bad = rec["n"] >= 15 and e.get("ev_lcb", 0) < 0 and e.get("ev", 0) < 0
    ch["alarms"] = ch.get("alarms", 0) + 1 if bad else 0
    memory_io.save(mem)
    print(json.dumps({"slot": slot, "n": rec["n"], "ev": e.get("ev"), "ev_lcb": e.get("ev_lcb"),
                      "alarms": ch["alarms"],
                      "action": "ROLLBACK via restore_filter (2 consecutive alarms)" if ch["alarms"] >= 2 else "ok"}, indent=1))


def cmd_adopt(a):
    mem = memory_io.load()
    run = json.load(open(a[0]))
    r = next(x for x in run["results"] if x["id"] == a[1])
    slot = str(r["slot"]); old = mem["slots"][slot]
    long_s, recent_s = parse_summary(r["long"]), parse_summary(r["recent"])
    lh = float(r.get("long_hours", run.get("long_hours", 168)))
    v = verdict(long_s, recent_s, lh)
    mem["slots"][slot] = {"family": r["family"], "preds": r.get("preds", []), "params": r.get("params", {}),
                          "condition": r["condition"], "previous_condition": old["condition"],
                          "deployed_at": NOW(), "failures": 0, "alarms": 0,
                          "baseline": {"hours": lh, "n": long_s["n"],
                                       "ev_lcb": v["long"].get("ev_lcb", 0), "source": NOW()}}
    memory_io.save(mem); print("adopted", a[1], "into slot", slot)


def cmd_note(a):
    mem = memory_io.load(); mem["facts"].append(f"[{NOW()[:10]}] " + " ".join(a)); memory_io.save(mem); print("noted")


def cmd_status(_):
    mem = memory_io.load()
    print("cycles:", len(mem["cycles"]), "| tested:", len(mem["tested"]), "| queue:", len(mem["queue"]))
    for s, c in mem["slots"].items():
        b = c["baseline"]
        print(f" slot {s} {c['family']:16s} base n={b['n']} {b['hours']}h ev_lcb={b['ev_lcb']} fail={c.get('failures')} alarm={c.get('alarms')}")
    best = sorted(mem["arms"].items(), key=lambda kv: -(kv[1]["wins"] / max(1, kv[1]["tests"])))[:5]
    print("top arms:", [(k, v["wins"], v["tests"]) for k, v in best])


if __name__ == "__main__":
    cmds = {"init": cmd_init, "eval": cmd_eval, "baseline": cmd_baseline, "watch": cmd_watch,
            "adopt": cmd_adopt, "note": cmd_note, "status": cmd_status}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print(__doc__); sys.exit(2)
    cmds[sys.argv[1]](sys.argv[2:])
