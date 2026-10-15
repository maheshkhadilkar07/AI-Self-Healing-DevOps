"""Technique 2 - Random Forest failure classification.

Trained on synthetic labelled symptom profiles (a real deployment would train on
labelled historical incidents). Features are made baseline-relative so the same
model works for any service / the live demo app.
"""
import numpy as np
from sklearn.ensemble import RandomForestClassifier

LABELS = ["normal", "cpu_overload", "memory_exhaustion", "container_crash",
          "bad_deployment", "database_failure"]

# (cpu, mem, error%, latency_ratio, rps_ratio)  -> (low, high) ranges
PROFILES = {
    "normal":            [(5, 50), (20, 60), (0, 1.5), (0.8, 1.4), (0.8, 1.2)],
    "cpu_overload":      [(55, 100), (20, 70), (0, 10), (1.8, 100), (0.4, 1.1)],
    "memory_exhaustion": [(15, 65), (78, 100), (0.5, 12), (1.0, 4), (0.5, 1.1)],
    "container_crash":   [(0, 6), (0, 12), (88, 100), (5, 100), (0, 0.08)],
    "bad_deployment":    [(15, 65), (20, 65), (15, 65), (1.2, 4.5), (0.6, 1.1)],
    "database_failure":  [(75, 100), (25, 75), (25, 85), (15, 100), (0.1, 0.75)],
}


def features(m, base):
    return [m["cpu"], m["mem"], m["error_rate"],
            min(m["latency"] / max(base["latency"], 1.0), 100.0),
            m["rps"] / max(base["rps"], 1.0)]


class FailureClassifier:
    def __init__(self, n_per_class=500, seed=7):
        rng = np.random.default_rng(seed)
        X, y = [], []
        for label, ranges in PROFILES.items():
            for _ in range(n_per_class):
                X.append([rng.uniform(lo, hi) for lo, hi in ranges])
                y.append(label)
        self.model = RandomForestClassifier(n_estimators=200, random_state=seed).fit(X, y)

    def predict(self, m, base):
        p = self.model.predict_proba([features(m, base)])[0]
        i = int(np.argmax(p))
        return self.model.classes_[i], float(p[i])

    FEATURE_NAMES = ["cpu", "mem", "error_rate", "latency_ratio", "rps_ratio"]

    def proba(self, m, base):
        p = self.model.predict_proba([features(m, base)])[0]
        return {c: round(float(x), 4) for c, x in zip(self.model.classes_, p)}

    def importances(self):
        return {n: round(float(v), 4) for n, v in zip(self.FEATURE_NAMES, self.model.feature_importances_)}
