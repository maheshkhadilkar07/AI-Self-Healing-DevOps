"""Simulated MERN-style microservice cluster with fault injection.

This lets the whole self-healing loop be demonstrated on any laptop with no
Docker / Kubernetes. The AI engine NEVER sees the injected fault - it only sees
metrics (cpu, mem, latency, error_rate, rps), exactly like a real Prometheus feed.
"""
import random
from .config import SERVICES, DEPENDENCIES

BASELINE = {
    "frontend": dict(cpu=20, mem=35, latency=80, err=0.4, rps=100),
    "api":      dict(cpu=30, mem=45, latency=120, err=0.5, rps=100),
    "auth":     dict(cpu=15, mem=30, latency=40, err=0.3, rps=60),
    "database": dict(cpu=35, mem=50, latency=20, err=0.2, rps=150),
}
# how fast each fault reaches full severity (per tick)
RISE = {"cpu_overload": 0.5, "memory_exhaustion": 0.2, "container_crash": 1.0,
        "bad_deployment": 0.6, "database_failure": 0.6}
FAULTS = list(RISE)


def _target(fault, b):
    """Metric values at full fault severity."""
    if fault == "cpu_overload":
        return dict(cpu=96, mem=b["mem"] + 5, latency=b["latency"] * 3.5, err=b["err"] + 2, rps=b["rps"] * 0.8)
    if fault == "memory_exhaustion":
        return dict(cpu=b["cpu"] + 15, mem=96, latency=b["latency"] * 2.2, err=b["err"] + 4, rps=b["rps"] * 0.85)
    if fault == "container_crash":
        return dict(cpu=0, mem=0, latency=3000, err=100, rps=0)
    if fault == "bad_deployment":
        return dict(cpu=b["cpu"] + 10, mem=b["mem"] + 3, latency=b["latency"] * 2.2, err=38, rps=b["rps"] * 0.9)
    if fault == "database_failure":
        return dict(cpu=92, mem=b["mem"] + 8, latency=b["latency"] * 80, err=55, rps=b["rps"] * 0.4)
    raise ValueError(fault)


class Simulator:
    name = "simulation"

    def __init__(self, services=None, deps=None, seed=None):
        self.services = services or SERVICES
        self.deps = deps or DEPENDENCIES
        self.rng = random.Random(seed)
        self.tick = 0
        self.state = {s: dict(fault=None, sev=0.0, healing=False, stubborn=False,
                              replicas=1, version="v2.0") for s in self.services}
        self.fault_tick = {}
        self.order = self._topo()
        self.last_signals = dict(logs=[], traces=[], events=[])
        self._extra_events = []

    def _topo(self):
        seen, order = set(), []
        def visit(s):
            if s in seen: return
            seen.add(s)
            for d in self.deps[s]: visit(d)
            order.append(s)
        for s in self.services: visit(s)
        return order  # dependencies first

    # ---------------- fault injection (used by dashboard / demo) ----------------
    def inject(self, service, fault, stubborn=False):
        if fault not in RISE: raise ValueError("unknown fault")
        if fault == "database_failure" and service != "database":
            raise ValueError("database_failure only applies to the database service")
        st = self.state[service]
        st.update(fault=fault, sev=0.0, healing=False, stubborn=stubborn)
        self.fault_tick[service] = self.tick
        return f"Injected {fault} into {service}" + (" (stubborn)" if stubborn else "")

    def clear_all(self):
        for st in self.state.values():
            st.update(fault=None, sev=0.0, healing=False, stubborn=False)
        self.fault_tick.clear()

    def ground_truth(self):
        return {s: st["fault"] for s, st in self.state.items() if st["fault"]}

    def fault_started(self, service):
        return self.fault_tick.get(service)

    # ---------------- metrics ----------------
    def _own(self, s):
        st, b, r = self.state[s], BASELINE[s], self.rng
        if st["fault"]:
            if st["healing"]:
                st["sev"] = max(0.0, st["sev"] - 0.4)
                if st["sev"] <= 0:
                    st.update(fault=None, healing=False)
                    self._extra_events.append(dict(service=s, type="Normal", msg="Started: container started, readiness probe passed"))
            else:
                st["sev"] = min(1.0, st["sev"] + RISE[st["fault"]])
        m = dict(cpu=b["cpu"] + r.gauss(0, 2.5), mem=b["mem"] + r.gauss(0, 1.5),
                 latency=b["latency"] * (1 + r.gauss(0, 0.03)),
                 err=max(0, b["err"] + r.gauss(0, 0.15)), rps=b["rps"] + r.gauss(0, 4))
        if st["fault"] and st["sev"] > 0:
            t = _target(st["fault"], b)
            for k in m:
                m[k] += st["sev"] * (t[k] - b[k])
        return m

    def collect(self):
        self.tick += 1
        out = {}
        for s in self.order:  # leaves first so failures cascade upward
            m = self._own(s)
            for d in self.deps[s]:
                dm, db = out[d], BASELINE[d]
                m["latency"] += 0.5 * max(0, dm["latency"] - db["latency"])
                m["err"] += 0.5 * max(0, dm["err"] - db["err"])
            out[s] = m
        res = {}
        for s, m in out.items():
            res[s] = dict(cpu=round(min(100, max(0, m["cpu"])), 1), mem=round(min(100, max(0, m["mem"])), 1),
                          latency=round(min(5000, max(0, m["latency"])), 1),
                          error_rate=round(min(100, max(0, m["err"])), 2),
                          rps=round(max(0, m["rps"]), 1),
                          replicas=self.state[s]["replicas"], version=self.state[s]["version"])
        self.last_signals = self._build_signals(res)
        return res

    # ---------------- logs / traces / k8s events (Observability layer: Logs, Traces, Events) ----------------
    def _build_signals(self, res):
        logs, events, traces = [], list(self._extra_events), []
        self._extra_events = []
        L = lambda s, lv, m: logs.append(dict(service=s, level=lv, msg=m))
        E = lambda s, t, m: events.append(dict(service=s, type=t, msg=m))
        L("frontend", "INFO", f"GET / 200 {res['frontend']['latency']:.0f}ms")
        for s in self.services:
            st = self.state[s]; f = st["fault"]
            if f and st["sev"] > 0.3 and not st["healing"]:
                if f == "cpu_overload":
                    L(s, "WARN", "event loop lag 480ms, request queue growing"); E(s, "Warning", "HighCPU: container cpu above 90% of limit")
                elif f == "memory_exhaustion":
                    L(s, "WARN", f"heap usage {res[s]['mem']:.0f}% - GC pressure")
                    if res[s]["mem"] > 85: L(s, "ERROR", "FATAL: JavaScript heap out of memory (approaching)")
                    E(s, "Warning", "MemoryPressure: working set near container limit")
                elif f == "container_crash":
                    L(s, "ERROR", "process exited with code 137 (SIGKILL)")
                    E(s, "Warning", "BackOff: restarting failed container"); E(s, "Warning", "Unhealthy: liveness probe failed: connection refused")
                elif f == "bad_deployment":
                    L(s, "ERROR", f"TypeError: Cannot read properties of undefined (release {st['version']})")
                    E(s, "Normal", f"ScalingReplicaSet: rollout to {st['version']}"); E(s, "Warning", "Unhealthy: readiness probe returned HTTP 500")
                elif f == "database_failure":
                    L(s, "ERROR", "connection pool exhausted (max 100), queries timing out"); E(s, "Warning", "SlowQuery: p99 latency above 1s")
            for d in self.deps[s]:
                bad = res[d]["error_rate"] > 10
                if bad: L(s, "ERROR", f"upstream '{d}' failing: request timeout")
                traces.append(dict(span=f"{s}->{d}", ms=res[d]["latency"], status="ERROR" if bad else "OK"))
        return dict(logs=logs, traces=traces, events=events)

    def signals(self):
        return self.last_signals


class SimExecutor:
    """Executes remediation actions against the simulator (stand-in for kubectl/Ansible/ArgoCD)."""

    def __init__(self, sim): self.sim = sim

    def execute(self, action, service, **kw):
        st = self.sim.state[service]
        helped = False
        if action == "restart":
            helped = st["fault"] in ("container_crash", "memory_exhaustion", "database_failure")
            msg = f"kubectl rollout restart deployment/{service}"
        elif action == "scale":
            st["replicas"] = min(5, st["replicas"] + 1)
            helped = st["fault"] == "cpu_overload"
            msg = f"kubectl scale deployment/{service} --replicas={st['replicas']}"
        elif action == "rollback":
            st["version"] = "v1.9"
            helped = st["fault"] == "bad_deployment"
            msg = f"argocd app rollback {service} (GitOps revert to v1.9)"
        else:
            return False, f"unknown action {action}"
        if helped and not st["stubborn"]:
            st["healing"] = True
        return True, msg
