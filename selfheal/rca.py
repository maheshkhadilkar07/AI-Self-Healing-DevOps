"""Technique 3 - Root-cause analysis: service-dependency graph + correlation analysis."""
import numpy as np


def _downstream_of(root, deps):
    """Services that (transitively) depend on `root`."""
    out, changed = set(), True
    while changed:
        changed = False
        for s, ds in deps.items():
            if s not in out and (root in ds or any(d in out for d in ds)):
                out.add(s); changed = True
    return out


def find_root_causes(anomalous, scores, history, deps, window=12):
    """anomalous: set of services currently anomalous. Returns ranked list of dicts."""
    cands = [s for s in anomalous if not any(d in anomalous for d in deps.get(s, []))]
    results = []
    for c in cands:
        affected = sorted(_downstream_of(c, deps) & set(anomalous))
        corr = {}
        lat_c = [h["latency"] for h in list(history[c])[-window:]]
        for a in affected:
            lat_a = [h["latency"] for h in list(history[a])[-window:]]
            n = min(len(lat_c), len(lat_a))
            if n >= 4 and np.std(lat_c[-n:]) > 0 and np.std(lat_a[-n:]) > 0:
                corr[a] = round(float(np.corrcoef(lat_c[-n:], lat_a[-n:])[0, 1]), 2)
        results.append(dict(service=c, affected=affected, correlation=corr, score=scores.get(c, 0)))
    results.sort(key=lambda r: r["score"])  # most anomalous first
    return results
