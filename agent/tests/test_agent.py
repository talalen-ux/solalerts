import json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import memory_io, ledger, candidates, strategies
from score import parse_summary, evaluate, verdict, wilson_lcb, subtract


class T(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        memory_io.PATH = os.path.join(self.tmp, "memory.json")
        ledger.cmd_init([])

    def test_wilson_monotone(self):
        self.assertLess(wilson_lcb(5, 10), 0.5)
        self.assertGreater(wilson_lcb(500, 1000), wilson_lcb(5, 10))

    def test_ev_negative_for_junk(self):
        s = parse_summary({"n": 152, "reached": {2: 10, 3: 5, 5: 4, 10: 3, 20: 1, 50: 1, 100: 0}})
        self.assertLess(evaluate(s)["ev_lcb"], 0)

    def test_ev_positive_for_runner_set(self):
        s = parse_summary({"n": 48, "reached": {2: 40, 3: 39, 5: 38, 10: 38, 20: 37, 50: 31, 100: 21}})
        self.assertGreater(evaluate(s)["ev_lcb"], 0)

    def test_subtract_halves(self):
        l = parse_summary({"n": 48, "reached": {2: 40, 3: 39, 5: 38, 10: 38, 20: 37, 50: 31, 100: 21}})
        r = parse_summary({"n": 13, "reached": {2: 10, 3: 9, 5: 9, 10: 9, 20: 8, 50: 8, 100: 5}})
        self.assertEqual(subtract(l, r)["n"], 35)

    def test_lint_blocks_honeypot_venue(self):
        bad = "launchpad = 'uniswap_v4' AND buyers >= 15 AND mc > 15000 AND mc < 200000"
        self.assertTrue(strategies.lint(bad))
        good = ledger.seed()["slots"]["155"]["condition"]
        self.assertEqual(strategies.lint(good), [])
        self.assertEqual(strategies.lint(ledger.seed()["slots"]["154"]["condition"]), [])

    def test_lint_blocks_null_and_leaky(self):
        c = ledger.seed()["slots"]["155"]["condition"] + " AND router_count >= 15"
        self.assertTrue(strategies.lint(c))
        c = ledger.seed()["slots"]["155"]["condition"] + " AND ath_x >= 3"
        self.assertTrue(strategies.lint(c))

    def test_propose_unique_and_linted(self):
        mem = memory_io.load()
        cs = candidates.propose(mem, k=6, seed=1)
        self.assertEqual(len(cs), 6)
        self.assertEqual(len({c["hash"] for c in cs}), 6)
        for c in cs:
            self.assertEqual(strategies.lint(c["condition"]), [])

    def test_eval_learns_and_dedupes(self):
        mem = memory_io.load()
        cs = candidates.propose(mem, k=2, seed=2)
        strong = {"n": 60, "reached": {2: 52, 3: 50, 5: 49, 10: 49, 20: 47, 50: 40, 100: 28}}
        recent = {"n": 20, "reached": {2: 17, 3: 17, 5: 16, 10: 16, 20: 15, 50: 13, 100: 9}}
        junk = {"n": 80, "reached": {2: 8, 3: 3, 5: 2, 10: 1, 20: 0, 50: 0, 100: 0}}
        rjunk = {"n": 30, "reached": {2: 3, 3: 1, 5: 1, 10: 0, 20: 0, 50: 0, 100: 0}}
        slot_hours = cs[0]["long_hours"]
        for c in cs[1:]:
            c["long_hours"] = slot_hours
        run = {"results": []}
        for i, c in enumerate(cs):
            run["results"].append({**c, "id": c["id"], "long": strong if i == 0 else junk,
                                   "recent": recent if i == 0 else rjunk})
        # make slot baselines comparable (same window) so the strong one can win
        for s in mem["slots"].values():
            s["baseline"]["hours"] = slot_hours; s["baseline"]["ev_lcb"] = 0.0
        mem["slots"][cs[0]["slot"]]["baseline"]["hours"] = slot_hours
        memory_io.save(mem)
        f = os.path.join(self.tmp, "run.json"); json.dump(run, open(f, "w"))
        ledger.cmd_eval([f])
        mem2 = memory_io.load()
        self.assertEqual(mem2["arms"][cs[0]["arm"]]["wins"], 1)
        self.assertEqual(mem2["arms"][cs[1]["arm"]]["wins"], 0)
        again = candidates.propose(mem2, k=10, seed=3)
        self.assertNotIn(cs[0]["hash"], {c["hash"] for c in again})


class Retired(unittest.TestCase):
    def test_retired_arm_skipped(self):
        tmp = tempfile.mkdtemp(); memory_io.PATH = os.path.join(tmp, "memory.json")
        ledger.cmd_init([])
        mem = memory_io.load()
        first = candidates.propose(mem, k=1, seed=5)[0]
        mem["arms"][first["arm"]] = {"tests": 9, "wins": 0, "sum_delta": 0, "retired": True}
        memory_io.save(mem)
        again = candidates.propose(memory_io.load(), k=20, seed=5)
        self.assertNotIn(first["arm"], {c["arm"] for c in again})


if __name__ == "__main__":
    unittest.main()
