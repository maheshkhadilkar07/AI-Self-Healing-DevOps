"""Technique 4 - Incident knowledge base with TF-IDF + cosine-similarity retrieval (the 'RAG' retriever)."""
import json, shutil
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from .config import KB_PATH, KB_SEED_PATH


def symptom_text(service, m, base):
    """Turn raw metrics into a short symptom description (the 'query document')."""
    t = [f"service_{service}"]
    if m["cpu"] > 80: t.append("cpu_saturated")
    if m["cpu"] < 6: t.append("cpu_zero")
    if m["mem"] > 78: t.append("memory_saturated")
    if m["mem"] < 8: t.append("memory_zero")
    lr = m["latency"] / max(base["latency"], 1)
    if lr > 15: t.append("latency_extreme")
    elif lr > 1.6: t.append("latency_high")
    if m["error_rate"] > 85: t.append("errors_total")
    elif m["error_rate"] > 10: t.append("errors_elevated")
    if m["rps"] < 0.1 * base["rps"]: t.append("traffic_dead")
    elif m["rps"] < 0.75 * base["rps"]: t.append("traffic_dropped")
    return " ".join(t)


class KnowledgeBase:
    def __init__(self):
        if not KB_PATH.exists():
            shutil.copy(KB_SEED_PATH, KB_PATH)
        self.load()

    def load(self):
        self.items = json.load(open(KB_PATH, encoding="utf-8"))
        self._fit()

    def _fit(self):
        self.vec = TfidfVectorizer(token_pattern=r"[A-Za-z_]+")
        self.matrix = self.vec.fit_transform([i["symptoms"] for i in self.items])

    def query(self, text, k=3):
        sims = cosine_similarity(self.vec.transform([text]), self.matrix)[0]
        order = sims.argsort()[::-1][:k]
        return [dict(self.items[i], similarity=round(float(sims[i]), 2)) for i in order if sims[i] > 0]

    def add(self, item):
        item["id"] = f"INC-{len(self.items) + 1:03d}"
        self.items.append(item)
        json.dump(self.items, open(KB_PATH, "w", encoding="utf-8"), indent=1)
        self._fit()  # continuous learning: KB grows with every resolved incident
        return item["id"]
