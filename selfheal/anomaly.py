"""Technique 1 - Isolation Forest anomaly detection (one model per service)."""
import numpy as np
from sklearn.ensemble import IsolationForest

FEATS = ["cpu", "mem", "latency", "error_rate", "rps"]


def vec(m):
    return [m[f] for f in FEATS]


class AnomalyDetector:
    def __init__(self):
        self.models, self.baseline, self.std = {}, {}, {}

    def fit(self, history):
        """history: {service: [metric dicts collected while system was healthy]}"""
        for svc, rows in history.items():
            X = np.array([vec(r) for r in rows], dtype=float)
            self.std[svc] = {f: max(float(X[:, i].std()), 0.05 * abs(float(X[:, i].mean())) + 0.5)
                             for i, f in enumerate(FEATS)}
            self.baseline[svc] = {f: float(X[:, i].mean()) for i, f in enumerate(FEATS)}
            self.models[svc] = IsolationForest(n_estimators=150, contamination=0.01,
                                               random_state=42).fit(X)

    def score(self, svc, m):
        """Returns (decision score, is_anomaly). Negative score => anomalous.

        Isolation Forest cannot tell *how far* a value is beyond its training range, so it is
        paired with a z-score guard (|z| > 6 on any metric) - a common hybrid in practice.
        """
        s = float(self.models[svc].decision_function(np.array([vec(m)], dtype=float))[0])
        b, sd = self.baseline[svc], self.std[svc]
        zmax = max(abs(m[f] - b[f]) / sd[f] for f in FEATS)
        if zmax > 6:
            s = min(s, -0.05 - min(zmax, 100) / 1000)
        return round(s, 4), s < 0
