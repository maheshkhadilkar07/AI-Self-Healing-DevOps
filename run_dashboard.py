"""Interactive web dashboard for the AI self-healing engine.
   python run_dashboard.py              -> simulation mode (no extra installs)
   python run_dashboard.py --mode live  -> real Node.js app, real crashes/restarts (needs Node 18+)
Open http://127.0.0.1:5000      History is stored in data/history.db and survives restarts.
"""
import argparse, atexit, csv, io, json, threading, time
from flask import Flask, jsonify, render_template, request, Response
from selfheal import config as C, audit
from selfheal.automation import AutomationRouter
from selfheal.engine import Engine
from selfheal.remediation import RULES
from selfheal.store import Store
from selfheal.simulator import FAULTS


def build(mode="sim", auto_approve=False, store=None, warmup=None):
    """Create (engine, target). Used by main() and by the tests."""
    if mode == "sim":
        from selfheal.simulator import Simulator, SimExecutor
        target = Simulator()
        services, deps, ex = C.SERVICES, C.DEPENDENCIES, AutomationRouter(SimExecutor(target))
    else:
        from selfheal.collectors import LiveTarget, LiveExecutor
        target = LiveTarget(); target.start(); atexit.register(target.stop)
        services, deps, ex = ["app"], {"app": []}, AutomationRouter(LiveExecutor(target))
    eng = Engine(target, ex, services, deps, auto_approve=auto_approve, store=store)
    eng.warmup(warmup or (C.WARMUP_TICKS if mode == "sim" else 30))
    return eng, target


SCENARIOS = {  # id: (title, description, [(delay_s, service, fault, stubborn)])
    "api_crash":    ("API container crash", "Pod dies; frontend errors cascade", [(0, "api", "container_crash", False)]),
    "db_outage":    ("Database outage", "Cascades to api + frontend; high-risk -> approval", [(0, "database", "database_failure", False)]),
    "mem_leak":     ("Memory leak (auth)", "Memory climbs until saturation", [(0, "auth", "memory_exhaustion", False)]),
    "bad_release":  ("Bad release (frontend)", "5xx errors after a deployment", [(0, "frontend", "bad_deployment", False)]),
    "traffic_spike": ("Traffic spike (api)", "CPU saturation -> scale out", [(0, "api", "cpu_overload", False)]),
    "double_fault": ("Double fault", "auth crash, then a bad release 25 s later", [(0, "auth", "container_crash", False), (25, "frontend", "bad_deployment", False)]),
    "unfixable":    ("Unfixable crash", "Fix doesn't work -> retry -> escalate to engineer", [(0, "api", "container_crash", True)]),
}
LIVE_OK = {"api_crash", "mem_leak", "bad_release", "traffic_spike"}


NAV = [("Project", [("home", "Home", "/"), ("project", "Project", "/project"), ("literature", "Literature Survey", "/literature"),
                   ("methodology", "Methodology", "/methodology"), ("references", "References", "/references")]),
       ("Live system", [("overview", "Overview", "/overview"), ("monitor", "Live Monitor", "/monitor"), ("architecture", "Architecture", "/architecture"),
                        ("incidents", "Incidents", "/incidents"), ("chaos", "Chaos Lab", "/chaos"), ("ai", "AI Lab", "/ai")]),
       ("Operations", [("policy", "Policy & Approvals", "/policy"), ("logs", "Logs & Events", "/logs"), ("audit", "Audit Trail", "/audit"),
                       ("reports", "Reports", "/reports"), ("settings", "Settings", "/settings")])]
TITLES = {slug: label for _, items in NAV for slug, label, _ in items}


def create_app(engine, target, mode, store):
    app = Flask(__name__, template_folder="selfheal/templates", static_folder="selfheal/static")
    q = lambda k, d="": request.args.get(k, d)

    @app.get("/", defaults={"slug": "home"})
    @app.get("/<slug>")
    def page(slug):
        if slug not in TITLES: return ("Not found", 404)
        return render_template(f"{slug}.html", page=slug, title=TITLES[slug], nav=NAV)

    @app.get("/api/state")
    def state(): return jsonify(engine.snapshot(int(q("n", 60))))

    @app.get("/api/incidents")
    def incidents(): return jsonify(store.list_incidents(q("q"), q("status"), q("type"), int(q("limit", 200))))

    @app.get("/api/incidents/<iid>")
    def incident(iid):
        cur = engine.incident
        if cur and cur["id"] == iid:
            return jsonify(json.loads(json.dumps(cur, default=str)))
        d = store.get_incident(iid)
        return (jsonify(d), 200) if d else (jsonify(error="not found"), 404)

    @app.get("/api/export/incidents.<fmt>")
    def export(fmt):
        rows = store.list_incidents(limit=100000)
        if fmt == "json":
            return Response(json.dumps(rows, indent=1), mimetype="application/json",
                            headers={"Content-Disposition": "attachment; filename=incidents.json"})
        buf = io.StringIO(); w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()) if rows else ["id"])
        w.writeheader(); w.writerows(rows)
        return Response(buf.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=incidents.csv"})

    @app.get("/api/logs")
    def logs(): return jsonify(store.signals(q("kind"), q("service"), q("level"), q("q"), int(q("limit", 200))))

    @app.get("/api/audit")
    def audit_api(): return jsonify(audit.search(int(q("limit", 300)), q("q"), q("event")))

    @app.get("/api/kb")
    def kb():
        text = q("q")
        items = engine.kb.query(text, 50) if text else [dict(i) for i in engine.kb.items][::-1]
        return jsonify(items)

    @app.get("/api/models")
    def models(): return jsonify(engine.models_info())

    @app.post("/api/whatif")
    def whatif():
        d = request.get_json()
        m = {k: float(d[k]) for k in ("cpu", "mem", "latency", "error_rate", "rps")}
        return jsonify(engine.whatif(d["service"], m))

    @app.get("/api/policy")
    def policy():
        pol = engine.policy
        stats = [dict(rule=f"{f}->{a}", ok=s[0], n=s[1], restricted=(s[1] >= 2 and s[0] / s[1] <= 0.5))
                 for (f, a), (s, n) in [((k), (v, v[1])) for k, v in pol.stats.items()]]
        rules = [dict(failure=f, action=a, why=w, risk=("high (database)" if (a == "restart" and f == "database_failure") else
                      "medium" if a == "rollback" else "low")) for f, (a, w) in RULES.items()]
        return jsonify(rules=rules, stats=stats, allowlist=sorted(["restart", "scale", "rollback"]),
                       limits=dict(consecutive_anomalies=C.CONSECUTIVE_ANOMALIES, verify_streak=C.VERIFY_STREAK,
                                   verify_timeout=C.VERIFY_TIMEOUT, max_attempts=C.MAX_ATTEMPTS, max_replicas=C.MAX_REPLICAS),
                       auto_approve=pol.auto_approve_high_risk)

    @app.get("/api/report")
    def report(): return jsonify(store.report(C.MANUAL_MTTR_SECONDS))

    @app.get("/api/scenarios")
    def scenarios():
        return jsonify([dict(id=k, title=v[0], desc=v[1]) for k, v in SCENARIOS.items() if mode == "sim" or k in LIVE_OK])

    @app.post("/api/scenario")
    def scenario():
        sid = request.get_json().get("id")
        if sid not in SCENARIOS or (mode == "live" and sid not in LIVE_OK):
            return jsonify(ok=False, msg="unknown scenario"), 400
        for delay, svc, fault, stub in SCENARIOS[sid][2]:
            svc = "app" if mode == "live" else svc
            if delay == 0: target.inject(svc, fault, stub)
            else: threading.Timer(delay, lambda s=svc, f=fault, st=stub: target.inject(s, f, st)).start()
        return jsonify(ok=True, msg=f"Scenario started: {SCENARIOS[sid][0]}")

    @app.post("/api/inject")
    def inject():
        d = request.get_json()
        try: return jsonify(ok=True, msg=target.inject(d["service"], d["fault"], d.get("stubborn", False)))
        except Exception as e: return jsonify(ok=False, msg=str(e)), 400

    @app.post("/api/settings")
    def settings():
        d = request.get_json()
        if "auto_approve" in d: engine.set_auto_approve(d["auto_approve"])
        if "paused" in d: engine.paused = bool(d["paused"])
        if "tick_seconds" in d: engine.tick_seconds = max(0.2, min(5.0, float(d["tick_seconds"])))
        return jsonify(ok=True)

    @app.post("/api/approve")
    def approve(): return jsonify(ok=engine.approve())

    @app.post("/api/reject")
    def reject(): return jsonify(ok=engine.reject())

    @app.post("/api/ack")
    def ack():
        if engine.incident and engine.incident["status"] == "escalated":
            target.clear_all()
        return jsonify(ok=engine.acknowledge_escalation())

    @app.post("/api/clear")
    def clear(): target.clear_all(); return jsonify(ok=True)

    @app.post("/api/history/clear")
    def clear_history(): store.clear(); return jsonify(ok=True)

    return app


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["sim", "live"], default="sim")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--auto-approve", action="store_true", help="auto-approve high-risk actions")
    args = ap.parse_args()
    store = Store()
    print("Learning healthy baseline...")
    engine, target = build(args.mode, args.auto_approve, store)
    print("Engine ready")

    def loop():
        while True:
            if not engine.paused:
                try: engine.step()
                except Exception as e: print("engine error:", e)
            time.sleep(engine.tick_seconds if args.mode == "sim" else max(0.1, engine.tick_seconds - 0.8))
    threading.Thread(target=loop, daemon=True).start()
    app = create_app(engine, target, args.mode, store)
    print(f"Dashboard: http://127.0.0.1:{args.port}")
    app.run(host="127.0.0.1", port=args.port, threaded=True)


if __name__ == "__main__":
    main()
