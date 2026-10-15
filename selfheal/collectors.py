"""Metric collectors / executors for the LIVE demo (real Node.js app + real process restarts)."""
import os, subprocess, sys, time, shutil
import requests

APP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "demo-app")
CHAOS = {"cpu_overload": "/chaos/cpu", "memory_exhaustion": "/chaos/memory",
         "container_crash": "/chaos/crash", "bad_deployment": "/chaos/bad-deploy"}


class LiveTarget:
    """Starts the Node demo app, probes it like Prometheus/blackbox would, and can restart/roll back/scale it."""
    name = "live"

    def __init__(self, port=3000):
        self.port, self.url = port, f"http://127.0.0.1:{port}"
        self.proc, self.version, self.replicas, self.faults = None, "v2.0-bad-capable", 1, {}
        self.tick = 0
        self._sig = dict(logs=[], traces=[], events=[])
        self._pending_events = [dict(service='app', type='Normal', msg='Started: node server.js')]

    def start(self, version=None):
        if shutil.which("node") is None:
            sys.exit("Node.js not found. Install Node 18+ or use --mode sim.")
        if not os.path.isdir(os.path.join(APP_DIR, "node_modules")):
            print("Installing demo-app dependencies (npm install)...")
            subprocess.check_call(["npm", "install", "--silent"], cwd=APP_DIR, shell=(os.name == "nt"))
        self.version = version or self.version
        env = {**os.environ, "PORT": str(self.port), "APP_VERSION": self.version}
        self.proc = subprocess.Popen(["node", "server.js"], cwd=APP_DIR, env=env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(40):
            try:
                if requests.get(self.url + "/health", timeout=0.5).ok:
                    return
            except Exception:
                time.sleep(0.25)
        sys.exit("Demo app failed to start")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try: self.proc.wait(3)
            except Exception: self.proc.kill()

    def collect(self):
        self.tick += 1
        n, lat, ok = 5, [], 0
        logs, events = [], list(self._pending_events)
        self._pending_events = []
        for _ in range(n):
            t = time.time()
            try:
                r = requests.get(self.url + "/api/items", timeout=2)
                lat.append((time.time() - t) * 1000)
                ok += r.status_code < 500
                if r.status_code >= 500 and len(logs) < 2: logs.append(dict(service='app', level='ERROR', msg=f'GET /api/items -> {r.status_code}'))
                elif lat[-1] > 400 and len(logs) < 2: logs.append(dict(service='app', level='WARN', msg=f'slow response {lat[-1]:.0f}ms (event loop blocked?)'))
            except Exception:
                lat.append(2000)
                if not logs: logs.append(dict(service='app', level='ERROR', msg='connection refused on :%d' % self.port))
        cpu = mem = 0.0
        try:
            j = requests.get(self.url + "/metrics.json", timeout=1).json()
            cpu, mem = j["cpu"], j["mem"]
        except Exception:
            pass
        time.sleep(0.3)
        if mem > 80: logs.append(dict(service='app', level='WARN', msg=f'rss at {mem:.0f}% of memory cap'))
        if ok == 0: events.append(dict(service='app', type='Warning', msg='Unhealthy: probe failed, no successful responses'))
        self._sig = dict(logs=logs, events=events, traces=[dict(span='probe->app', ms=round(sum(lat) / n, 1), status='OK' if ok else 'ERROR')])
        return {"app": dict(cpu=round(cpu, 1), mem=round(mem, 1), latency=round(sum(lat) / n, 1),
                            error_rate=round(100 * (n - ok) / n, 1), rps=round(100 * ok / n, 1),
                            replicas=self.replicas, version=self.version)}

    def signals(self): return self._sig

    # --- fault injection for the demo
    def inject(self, service, fault, stubborn=False):
        if fault not in CHAOS:
            raise ValueError(f"{fault} not supported in live mode (use cpu_overload, memory_exhaustion, container_crash, bad_deployment)")
        try: requests.post(self.url + CHAOS[fault], timeout=1)
        except Exception: pass
        self.faults["app"] = fault
        self.fault_tick = self.tick
        return f"Injected {fault} into the live Node app"

    def fault_started(self, service): return getattr(self, "fault_tick", None)
    def ground_truth(self): return dict(self.faults)
    def clear_all(self):
        self.faults.clear(); self.replicas = 1
        self.stop(); self.start("v2.0-bad-capable")


class LiveExecutor:
    def __init__(self, target): self.t = target

    def execute(self, action, service, **kw):
        t = self.t
        if action == "restart":
            t.stop(); t.start(); t.faults.clear()
            return True, "restarted Node process (stand-in for: kubectl rollout restart)"
        if action == "rollback":
            t.stop(); t.start("v1.9-stable"); t.faults.clear()
            return True, "restarted app on last good version v1.9-stable (stand-in for: argocd app rollback)"
        if action == "scale":
            t.replicas += 1
            try: requests.post(t.url + "/admin/scale", json={"replicas": t.replicas}, timeout=1)
            except Exception: pass
            t.faults.clear()
            return True, f"scaled to {t.replicas} replicas (emulated by load redistribution in demo app)"
        return False, "unknown action"
