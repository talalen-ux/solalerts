import pickle, math, numpy as np, sys
sys.path.insert(0, "/home/user/solalerts")
from football.model import MAX_GOALS
rows = pickle.load(open(sys.argv[1], "rb"))
def feats(r, spec):
    ld = math.log1p(r['km']/100)
    fh = np.array([ld if 'dist' in spec else 0, r['h_att'] if 'form' in spec else 0, r['a_def'] if 'form' in spec else 0])
    fa = np.array([-ld if 'dist' in spec else 0, r['a_att'] if 'form' in spec else 0, r['h_def'] if 'form' in spec else 0])
    return fh, fa
def fit(train, spec):
    b = np.zeros(3)
    for _ in range(30):
        g = np.zeros(3); H = np.eye(3)*1e-3
        for r in train:
            fh, fa = feats(r, spec)
            for y, base, f in ((r['hg'], r['lam'], fh), (r['ag'], r['mu'], fa)):
                l = base*math.exp(b@f); g += (y-l)*f; H += l*np.outer(f, f)
        b += np.linalg.solve(H, g)
    return b
from scipy_free import outcome_ll  # local helper
for test in (2023, 2024, 2025):
    train = [r for r in rows if r['season'] != test]; te = [r for r in rows if r['season'] == test]
    base = np.mean([outcome_ll(r, r['lam'], r['mu']) for r in te], axis=0)
    line = f"test {test}: base 1X2 {base[0]:.4f} O2.5 {base[1]:.4f}"
    for spec in (('dist',), ('form',), ('dist','form')):
        b = fit(train, spec)
        ll = []
        for r in te:
            fh, fa = feats(r, spec)
            ll.append(outcome_ll(r, r['lam']*math.exp(b@fh), r['mu']*math.exp(b@fa)))
        ll = np.mean(ll, axis=0)
        line += f" | {'+'.join(spec)} b={np.round(b,3)} 1X2 {ll[0]-base[0]:+.4f} O2.5 {ll[1]-base[1]:+.4f}"
    print(line)
