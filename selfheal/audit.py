"""Append-only audit log (JSON lines) - every AI decision and action is recorded."""
import json, time, threading
from .config import AUDIT_PATH

_lock = threading.Lock()

def log(event: str, **details):
    rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "event": event, **details}
    with _lock:
        with open(AUDIT_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")
    return rec

def tail(n=15):
    try:
        with open(AUDIT_PATH, encoding="utf-8") as f:
            lines = f.readlines()[-n:]
        return [json.loads(l) for l in lines]
    except FileNotFoundError:
        return []


def search(n=300, q="", event=""):
    try:
        with open(AUDIT_PATH, encoding="utf-8") as f:
            recs = [json.loads(l) for l in f]
    except FileNotFoundError:
        return []
    if event: recs = [r for r in recs if r.get("event") == event]
    if q: recs = [r for r in recs if q.lower() in json.dumps(r).lower()]
    return recs[-n:][::-1]
