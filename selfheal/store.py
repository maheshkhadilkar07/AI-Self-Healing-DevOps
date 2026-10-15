"""Persistent history (SQLite, stdlib only): incidents, metrics, logs/events, health ticks.
Survives restarts - the dashboard's Incidents / Logs / Reports pages read from here."""
import json, sqlite3, threading, time
from .config import DATA_DIR

DB_PATH = DATA_DIR / "history.db"
SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY, started TEXT, mode TEXT);
CREATE TABLE IF NOT EXISTS ticks(run INT, tick INT, ts TEXT, healthy INT);
CREATE TABLE IF NOT EXISTS metrics(run INT, tick INT, ts TEXT, service TEXT, cpu REAL, mem REAL, latency REAL,
  err REAL, rps REAL, score REAL, anomalous INT);
CREATE INDEX IF NOT EXISTS ix_metrics ON metrics(service, tick);
CREATE TABLE IF NOT EXISTS signals(id INTEGER PRIMARY KEY AUTOINCREMENT, run INT, tick INT, ts TEXT, kind TEXT,
  service TEXT, level TEXT, msg TEXT);
CREATE TABLE IF NOT EXISTS incidents(id TEXT PRIMARY KEY, run INT, num INT, ts TEXT, status TEXT, root TEXT,
  failure_type TEXT, action TEXT, confidence REAL, attempts INT, mttr REAL, mttd REAL, data TEXT);
"""
now = lambda: time.strftime("%Y-%m-%d %H:%M:%S")


class Store:
    def __init__(self, path=None):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path or DB_PATH), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self._n = 0

    # ---------------- writes
    def start_run(self, mode):
        with self.lock:
            cur = self.db.execute("INSERT INTO runs(started, mode) VALUES(?,?)", (now(), mode))
            self.db.commit()
            return cur.lastrowid

    def max_num(self):
        with self.lock:
            return self.db.execute("SELECT COALESCE(MAX(num),0) FROM incidents").fetchone()[0]

    def add_tick(self, run, tick, metrics, scores, anoms, healthy):
        ts = now()
        with self.lock:
            self.db.executemany("INSERT INTO metrics VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                [(run, tick, ts, s, m["cpu"], m["mem"], m["latency"], m["error_rate"], m["rps"], scores[s], int(anoms[s]))
                 for s, m in metrics.items()])
            self.db.execute("INSERT INTO ticks VALUES(?,?,?,?)", (run, tick, ts, int(healthy)))
            self.db.commit()
            self._n += 1
            if self._n % 300 == 0:   # keep the DB small
                self.db.execute("DELETE FROM metrics WHERE rowid < (SELECT MAX(rowid) FROM metrics) - 80000")
                self.db.execute("DELETE FROM ticks WHERE rowid < (SELECT MAX(rowid) FROM ticks) - 40000")
                self.db.execute("DELETE FROM signals WHERE id < (SELECT MAX(id) FROM signals) - 40000")
                self.db.commit()

    def add_signal(self, run, tick, kind, service, level, msg):
        with self.lock:
            self.db.execute("INSERT INTO signals(run,tick,ts,kind,service,level,msg) VALUES(?,?,?,?,?,?,?)",
                            (run, tick, now(), kind, service, level, msg))
            self.db.commit()

    def save_incident(self, inc, run):
        num = int(inc["id"].split("-")[1])
        with self.lock:
            self.db.execute("""INSERT INTO incidents(id,run,num,ts,status,root,failure_type,action,confidence,attempts,mttr,mttd,data)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET status=excluded.status, action=excluded.action, attempts=excluded.attempts,
                  mttr=excluded.mttr, mttd=excluded.mttd, data=excluded.data""",
                (inc["id"], run, num, now(), inc["status"], inc["root"], inc["failure_type"], inc["action"],
                 inc["confidence"], inc["attempts"], inc.get("mttr"), inc.get("mttd"), json.dumps(inc, default=str)))
            self.db.commit()

    # ---------------- reads
    def list_incidents(self, q="", status="", ftype="", limit=200):
        sql, args = "SELECT id,run,ts,status,root,failure_type,action,confidence,attempts,mttr,mttd FROM incidents WHERE 1=1", []
        if status: sql += " AND status=?"; args.append(status)
        if ftype: sql += " AND failure_type=?"; args.append(ftype)
        if q:
            sql += " AND (id LIKE ? OR root LIKE ? OR failure_type LIKE ? OR action LIKE ? OR data LIKE ?)"
            args += [f"%{q}%"] * 5
        sql += " ORDER BY num DESC LIMIT ?"; args.append(limit)
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def get_incident(self, iid):
        with self.lock:
            r = self.db.execute("SELECT data FROM incidents WHERE id=?", (iid,)).fetchone()
        return json.loads(r[0]) if r else None

    def signals(self, kind="", service="", level="", q="", limit=200):
        sql, args = "SELECT ts,tick,kind,service,level,msg FROM signals WHERE 1=1", []
        for col, v in (("kind", kind), ("service", service), ("level", level)):
            if v: sql += f" AND {col}=?"; args.append(v)
        if q: sql += " AND msg LIKE ?"; args.append(f"%{q}%")
        sql += " ORDER BY id DESC LIMIT ?"; args.append(limit)
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def report(self, manual_mttr=900):
        with self.lock:
            inc = [dict(r) for r in self.db.execute(
                "SELECT id,status,failure_type,action,mttr,mttd,attempts FROM incidents ORDER BY num").fetchall()]
            h = self.db.execute("SELECT AVG(healthy), COUNT(*) FROM ticks").fetchone()
        res = [i for i in inc if i["status"] == "resolved" and i["mttr"] is not None]
        avg = lambda xs: round(sum(xs) / len(xs), 1) if xs else None
        by = lambda k: {v: sum(1 for i in inc if i[k] == v) for v in sorted({i[k] for i in inc})}
        avg_mttr = avg([i["mttr"] for i in res])
        return dict(total=len(inc), resolved=len(res), escalated=sum(i["status"] in ("escalated", "closed_by_human") for i in inc),
                    avg_mttr=avg_mttr, min_mttr=min([i["mttr"] for i in res], default=None),
                    max_mttr=max([i["mttr"] for i in res], default=None),
                    avg_mttd=avg([i["mttd"] for i in inc if i["mttd"] is not None]),
                    availability=round(100 * h[0], 2) if h[0] is not None else None, ticks=h[1],
                    faster_pct=round(100 * (1 - avg_mttr / manual_mttr), 1) if avg_mttr else None, manual_mttr=manual_mttr,
                    by_type=by("failure_type"), by_action=by("action"), by_status=by("status"),
                    timeline=[dict(id=i["id"], mttr=i["mttr"], type=i["failure_type"], status=i["status"]) for i in inc[-30:]])

    def action_stats(self):
        with self.lock:
            rows = self.db.execute("SELECT failure_type, action, SUM(status='resolved'), COUNT(*) FROM incidents "
                                   "WHERE status IN ('resolved','escalated','closed_by_human') GROUP BY failure_type, action").fetchall()
        return {(r[0], r[1]): [int(r[2]), int(r[3])] for r in rows}

    def clear(self):
        with self.lock:
            for t in ("ticks", "metrics", "signals", "incidents"):
                self.db.execute(f"DELETE FROM {t}")
            self.db.commit()
