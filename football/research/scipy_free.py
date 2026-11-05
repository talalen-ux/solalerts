import math, numpy as np
def pmf(l, k): return np.exp(k*math.log(l) - l - np.array([math.lgamma(x+1) for x in k]))
K = np.arange(11)
def outcome_ll(r, lam, mu):
    M = np.outer(pmf(lam, K), pmf(mu, K)); rho = r['rho']
    M[0,0]*=1-lam*mu*rho; M[0,1]*=1+lam*rho; M[1,0]*=1+mu*rho; M[1,1]*=1-rho; M/=M.sum()
    i, j = np.indices(M.shape)
    p = {'H': M[i>j].sum(), 'D': M[i==j].sum(), 'A': M[i<j].sum()}
    o = 'H' if r['hg']>r['ag'] else 'D' if r['hg']==r['ag'] else 'A'
    t = M[(i+j)>2].sum(); over = r['hg']+r['ag']>2
    return -math.log(p[o]), -math.log(t if over else 1-t)
