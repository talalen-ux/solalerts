#!/usr/bin/env python3
"""Propose the next experiments. Thompson sampling over mutation arms, learned
from memory.json, so the agent spends its backtest budget where changes have paid."""
import copy, json, random, sys
import memory_io
from strategies import FAMILIES, PREDICATES, render, lint, cond_hash


def arm_stats(mem, arm):
    a = mem["arms"].get(arm, {"tests": 0, "wins": 0, "sum_delta": 0.0})
    return a


def thompson(mem, arm, rng):
    a = arm_stats(mem, arm)
    return rng.betavariate(1 + a["wins"], 1 + a["tests"] - a["wins"])


def neighbours(family, params):
    grid = FAMILIES[family]["grid"]
    for name, values in grid.items():
        cur = params[name]
        if cur not in values:
            continue
        i = values.index(cur)
        if i > 0:
            yield f"{family}:{name}:down", name, values[i - 1]
        if i < len(values) - 1:
            yield f"{family}:{name}:up", name, values[i + 1]


def propose(mem, k=4, seed=None):
    rng = random.Random(seed)
    tested = mem["tested"]
    pool = []
    # 1) queued free-form hypotheses written by the agent itself get priority
    for q in list(mem.get("queue", [])):
        cond = q["condition"]
        if cond_hash(cond) in tested or lint(cond):
            continue
        pool.append((9.0, {"id": q["id"], "slot": q["slot"], "family": q.get("family", "freeform"),
                           "arm": q.get("arm", "queue"), "condition": cond, "preds": []}))
    # 2) mutations of each slot's champion
    for slot, ch in mem["slots"].items():
        fam = ch.get("family")
        if fam not in FAMILIES:
            continue
        base_params, base_preds = ch["params"], ch.get("preds", [])
        for arm, name, val in neighbours(fam, base_params):
            p = copy.deepcopy(base_params)
            p[name] = val
            cond = render(fam, p, base_preds)
            pool.append((thompson(mem, arm, rng), {"slot": slot, "family": fam, "arm": arm,
                                                   "params": p, "preds": base_preds, "condition": cond}))
        for pname in PREDICATES:
            if pname in base_preds:
                continue
            arm = f"{fam}:pred:{pname}"
            preds = base_preds + [pname]
            cond = render(fam, base_params, preds)
            pool.append((thompson(mem, arm, rng), {"slot": slot, "family": fam, "arm": arm,
                                                   "params": base_params, "preds": preds, "condition": cond}))
    out, seen_arms = [], set()
    for score, c in sorted(pool, key=lambda x: -x[0]):
        h = cond_hash(c["condition"])
        if h in tested or lint(c["condition"]) or c["arm"] in seen_arms:
            continue
        if mem["arms"].get(c["arm"], {}).get("retired"):
            continue
        c["hash"] = h
        w = FAMILIES.get(c["family"], {}).get("windows", {"long": 168, "recent": 72})
        c["long_hours"], c["recent_hours"] = w["long"], w["recent"]
        c.setdefault("id", f"c{len(out) + 1}-{h[:6]}")
        out.append(c)
        seen_arms.add(c["arm"])
        if len(out) >= k:
            break
    return out


if __name__ == "__main__":
    mem = memory_io.load()
    if mem is None:
        sys.exit("run: python3 ledger.py init")
    k = int(sys.argv[sys.argv.index("--k") + 1]) if "--k" in sys.argv else 4
    print(json.dumps(propose(mem, k), indent=1))
