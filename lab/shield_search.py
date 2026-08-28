#!/usr/bin/env python3
"""SHIELD LAB - the self-improving sub-2x removal loop.

Usage:  python3 shield_search.py <exports_dir> [--universe NAME=file.xlsx ...]

For every row-level backtest export (one export == one filter universe):
  1. engineer features (honest-xs, ratios, bundle family)
  2. scan every numeric feature x quantile threshold x direction
  3. keep legs passing ALL bars:
       - junk cut  >= 3% of sub-2x rows
       - winner cost <= 1/3 of junk cut (and <= ~1%abs preferred)
       - improves (or holds) 2x+ rate in EVERY week with n>=80
       - zero vetoed live-winner mints removed
       - <= ~5% of 10x+ tail removed per leg
  4. greedy-stack surviving legs, re-checking jointly
  5. emit report + paste-ready SQL

Doctrine (learned 2026-08, do not relax silently):
  * honest xs: xs_h = xs if current_ath_slot > entry_slot else 1.0
  * universe purity: legs derive ONLY from the target filter's own export
  * cross-universe transfer must be re-verified, never assumed
  * live-engine backtest confirmation required before deployment
  * a leg that fails weekly stability is regime-fit: reject
"""
import sys, glob, os
import pandas as pd, numpy as np
import warnings; warnings.filterwarnings('ignore')

VETO_FILE = os.path.join(os.path.dirname(__file__), 'veto_mints.txt')
VETO = [l.split('#')[0].strip() for l in open(VETO_FILE) if l.split('#')[0].strip()] if os.path.exists(VETO_FILE) else []

RATIOS = {
    'sb_ratio':  ('sellers','buyers'), 'churn2': ('buys','buyers'),
    'svbv2': ('sell_volume','buy_volume'), 'mc_over_launch': ('mc','launch_mc'),
    'bundle_sol_per_lp': ('max_bundle_sol','lp_sol'),
}
FEATS = ['buyers','sellers','buys','sells','buy_volume_1m','buy_volume','sell_volume','lp_sol','lp_ratio',
 'launch_mc','launch_bundle_pct','max_launch_bundle_pct','max_bundle_sol','fresh_holding_pct',
 'max_fresh_holding_pct','cnt_from_cex','cnt_new','med_makers','cnt_distinct_makers','program_ids_count',
 'program_ids_stddev','top_source','dev_deploys','dev_migrated','owner_age','owner_tx','owner_balance',
 'origin_balance','rugcheck_score','dist_prio','dist_tip','max_tip','med_tip','network_fees','kol_buyers',
 'lp_sol_launch','image_hash_count','uri_count','mc','bonding_progress'] + list(RATIOS)

def engineer(df):
    df = df.copy()
    df['xs_h'] = np.where(df.current_ath_slot > df.entry_slot, df['xs'], 1.0)
    if {'updated_slot','created_slot'} <= set(df.columns):
        df['age_slots'] = df.updated_slot - df.created_slot
    for name,(a,b) in RATIOS.items():
        if a in df and b in df:
            df[name] = pd.to_numeric(df[a],errors='coerce') / pd.to_numeric(df[b],errors='coerce').replace(0,np.nan)
    df['week'] = pd.to_datetime(df.snapshot_at, utc=True, format='mixed').dt.isocalendar().week
    return df

def weekly_ok(df, keep):
    for wk, g in df.groupby('week'):
        if len(g) < 80: continue
        gk = g[keep.reindex(g.index).fillna(False)]
        if len(gk) < 20: return False
        if (gk.xs_h>=2).mean() < (g.xs_h>=2).mean() - 0.005: return False
    return True

def scan(df, label):
    df = engineer(df)
    n0, win0 = len(df), (df.xs_h>=2)
    t10_0 = int((df.xs_h>=10).sum())
    picked, cur = [], df
    for _ in range(6):
        best = None
        win = cur.xs_h >= 2
        for f in [f for f in FEATS if f in cur.columns]:
            v = pd.to_numeric(cur[f], errors='coerce')
            for thr in v.quantile([.02,.05,.1,.15,.85,.9,.95,.98]).dropna().unique():
                for d in ('gt','lt'):
                    cut = ((v>thr) if d=='gt' else (v<thr)).fillna(False)
                    j, w = cut[~win].mean(), cut[win].mean()
                    if j < 0.03 or w > j/3 or w > 0.03: continue
                    if cut[cur.xs_h>=10].sum() > max(1, 0.05*t10_0): continue
                    if 'mint' in cur and cut[cur.mint.isin(VETO)].any(): continue
                    if not weekly_ok(cur, ~cut): continue
                    score = j - 4*w
                    if best is None or score > best[0]:
                        best = (score, f, d, float(thr), j, w)
        if best is None: break
        _, f, d, thr, j, w = best
        v = pd.to_numeric(cur[f], errors='coerce')
        cur = cur[~(((v>thr) if d=='gt' else (v<thr)).fillna(False))]
        picked.append((f, d, thr, j, w))
    print(f"\n=== {label}: n={n0}  2x+ {100*win0.mean():.1f}%")
    if not picked:
        print("    fully distilled - no leg passes the bars (expected for mature filters)")
    for f,d,thr,j,w in picked:
        op = '>' if d=='gt' else '<'
        print(f"    CUT {f} {op} {thr:.4g}   junk -{100*j:.1f}%  winners -{100*w:.2f}%")
        print(f"      SQL: AND NOT ({f} {op} {thr:.4g})   -- NULL-guard before deploying")
    if picked:
        x = cur.xs_h.values
        print(f"    RESULT: n {n0} -> {len(cur)}  2x+ {100*win0.mean():.1f}% -> {100*(x>=2).mean():.1f}%  "
              f"10x+ kept {int((x>=10).sum())}/{t10_0}")
    return picked

if __name__ == '__main__':
    d = sys.argv[1] if len(sys.argv) > 1 else '.'
    for f in sorted(glob.glob(os.path.join(d,'*.xlsx'))):
        try:
            df = pd.read_excel(f)
            if 'xs' not in df or 'snapshot_at' not in df: continue
            scan(df, os.path.basename(f))
        except Exception as e:
            print(f"skip {f}: {e}")
