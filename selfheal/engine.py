"""The self-healing control loop:  Monitor -> Detect -> Decide -> Heal -> Verify -> Learn."""
import threading
from collections import deque
from . import audit, config as C
from .anomaly import AnomalyDetector
from .classifier import FailureClassifier, features
from .rca import find_root_causes
from .knowledge_base import KnowledgeBase, symptom_text
from .policy import PolicyEngine
from .remediation import plan
from .verifier import check
from .explain import explain
from .events import EventRouter


class Engine:
    def __init__(self, collector, executor, services, deps, auto_approve=False, store=None):
        self.collector, self.executor = collector, executor
        self.services, self.deps = services, deps
        self.tick = 0
        self.history = {s: deque(maxlen=600) for s in services}
        self.consec = {s: 0 for s in services}
        self.detector, self.classifier = AnomalyDetector(), FailureClassifier()
        self.kb = KnowledgeBase()
        self.policy = PolicyEngine(auto_approve)
        if store:
            self.policy.stats = store.action_stats()   # learned success rates persist
        self.incident = None
        self.closed = []
        self.lock = threading.RLock()
        self.store = store
        self.run = store.start_run(getattr(collector, "name", "?")) if store else 0
        self.counter = store.max_num() if store else 0   # incident ids continue across restarts
        self.paused, self.tick_seconds = False, C.TICK_SECONDS
        self.ready = False
        # Kafka-style event router: telemetry + decisions flow through topics
        self.router = EventRouter()
        self.logs, self.events_buf, self.traces = deque(maxlen=80), deque(maxlen=40), deque(maxlen=40)
        self.router.subscribe("telemetry.logs", self._on_log)
        self.router.subscribe("telemetry.events", self._on_event)
        self.router.subscribe("telemetry.traces", self.traces.append)
        self.router.subscribe("telemetry.metrics", self._on_metrics)

    # ------------------------------------------------------------ setup
    def warmup(self, n=C.WARMUP_TICKS):
        healthy = {s: [] for s in self.services}
        for _ in range(n):
            self.tick += 1  # keep engine clock aligned with the collector clock
            m = self.collector.collect()
            for s in self.services:
                healthy[s].append(m[s])
        self.detector.fit(healthy)
        self.ready = True
        audit.log("engine_ready", services=self.services, samples=n)

    # ------------------------------------------------------------ main loop
    def step(self):
        with self.lock:
            self.tick += 1
            metrics = self.collector.collect()
            sig = self.collector.signals() if hasattr(self.collector, "signals") else {}
            for kind in ("logs", "events", "traces"):
                for item in sig.get(kind, []):
                    self.router.publish(f"telemetry.{kind}", {**item, "tick": self.tick})
            self.router.publish("telemetry.metrics", {"tick": self.tick, "metrics": metrics})
            return metrics

    def _on_log(self, m):
        self.logs.append(m)
        if self.store and m["level"] != "INFO":
            self.store.add_signal(self.run, m["tick"], "log", m["service"], m["level"], m["msg"])

    def _on_event(self, m):
        self.events_buf.append(m)
        if self.store:
            self.store.add_signal(self.run, m["tick"], "event", m["service"], m["type"], m["msg"])

    def _on_metrics(self, msg):
        """AI core: consumes telemetry.metrics from the router."""
        metrics, scores, anoms = msg["metrics"], {}, {}
        for s in self.services:
            score, anom = self.detector.score(s, metrics[s])
            scores[s] = score
            anoms[s] = anom
            self.history[s].append({**metrics[s], "score": score, "anomalous": anom, "tick": self.tick})
            self.consec[s] = self.consec[s] + 1 if anom else 0
        if self.store:
            self.store.add_tick(self.run, self.tick, metrics, scores, anoms, check(metrics, self.detector.baseline)[0])
        if self.incident is None:
            self._detect(scores)
        else:
            self._advance(metrics)

    def _pub(self, topic, **msg):
        self.router.publish(topic, {"tick": self.tick, **msg})

    # ------------------------------------------------------------ detect + diagnose + decide
    def _detect(self, scores):
        anomalous = {s for s in self.services if self.consec[s] >= C.CONSECUTIVE_ANOMALIES}
        if not anomalous:
            return
        roots = find_root_causes(anomalous, scores, self.history, self.deps)
        root = roots[0]
        svc = root["service"]
        recent = list(self.history[svc])[-2:]
        avg = {k: sum(r[k] for r in recent) / len(recent) for k in ("cpu", "mem", "latency", "error_rate", "rps")}
        base = self.detector.baseline[svc]
        label, conf = self.classifier.predict(avg, base)
        if label == "normal":
            return  # statistical outlier but symptoms look benign - keep watching
        sym = symptom_text(svc, avg, base)
        def uniq(items, fmt):
            out = []
            for i in items:
                t = fmt(i)
                if t not in out: out.append(t)
            return out[-3:]
        ev_logs = uniq([l for l in self.logs if l["service"] == svc and self.tick - l["tick"] <= 8 and l["level"] != "INFO"], lambda l: f"{l['level']} {l['msg']}")
        ev_events = uniq([e for e in self.events_buf if e["service"] == svc and self.tick - e["tick"] <= 8], lambda e: f"{e['type']}: {e['msg']}")
        matches = self.kb.query(sym, 3)
        action, why = plan(label)
        self.counter += 1
        inc = dict(id=f"EVT-{self.counter:03d}", status="diagnosed", root=svc, affected=root["affected"],
                   correlation=root["correlation"], failure_type=label, confidence=conf, symptoms=sym,
                   kb_matches=matches, action=action, action_why=why, attempts=0,
                   t_detect=self.tick, mttd=None, t_fault=self.collector.fault_started(svc) if hasattr(self.collector, "fault_started") else None,
                   timeline=[], anomalous=sorted(anomalous), logs=ev_logs, events=ev_events, metrics_at_detection={k: round(v, 1) for k, v in avg.items()})
        if inc["t_fault"] is not None:
            inc["mttd"] = (self.tick - inc["t_fault"]) * C.TICK_SECONDS
        inc["explanation"], inc["explainer"] = explain(inc)
        self.incident = inc
        self._note(f"Anomaly detected on {', '.join(sorted(anomalous))} (Isolation Forest)")
        self._note(f"Root cause: {svc} (dependency graph); affected: {', '.join(root['affected']) or 'none'}")
        if ev_logs: self._note("Log evidence: " + ev_logs[-1])
        if ev_events: self._note("K8s event: " + ev_events[-1])
        self._note(f"Classified as {label} ({conf:.0%}) by Random Forest")
        if matches:
            self._note(f"Similar past incident {matches[0]['id']} (cosine {matches[0]['similarity']}) -> '{matches[0]['action']}'")
        self._pub("ai.anomalies", services=sorted(anomalous), scores={k: scores[k] for k in anomalous})
        self._pub("ai.diagnosis", id=inc["id"], root=svc, failure=label, confidence=round(conf, 2))
        audit.log("diagnosis", id=inc["id"], root=svc, failure=label, confidence=round(conf, 2), action=action)
        self._decide()

    def _decide(self):
        inc = self.incident
        replicas = self._replicas(inc["root"])
        steps = self.executor.describe(inc["action"], inc["root"]) if hasattr(self.executor, "describe") else []
        inc["plan_steps"] = steps
        if steps:
            self._note("Remediation plan: " + " -> ".join(x["tool"] for x in steps))
            self._pub("automation.plan", id=inc["id"], steps=[x["tool"] for x in steps])
        pol = self.policy.evaluate(self.tick, inc["action"], inc["root"], inc["failure_type"], replicas)
        inc["policy"] = pol
        self._pub("policy.decision", id=inc["id"], decision=pol["decision"], risk=pol["risk"])
        audit.log("policy", id=inc["id"], **pol)
        if pol["decision"] == "approved":
            self._note(f"Policy engine approved '{inc['action']}' (risk: {pol['risk']})")
            self._execute()
        elif pol["decision"] == "needs_approval":
            inc["status"] = "pending_approval"
            why = "LEARNED POLICY (low past success)" if pol["risk"] == "learned" else "HIGH RISK"
            self._note(f"{why} - waiting for human approval of '{inc['action']}'")
        else:
            inc["status"] = "escalated"
            self._note("Policy DENIED action -> escalated to human: " + "; ".join(pol["reasons"]))
            audit.log("escalated", id=inc["id"], reasons=pol["reasons"])

    def _execute(self):
        inc = self.incident
        inc["attempts"] += 1
        ok, msg = self.executor.execute(inc["action"], inc["root"])
        self.policy.record_action(self.tick, inc["root"], inc["action"])
        inc["dispatched"] = getattr(self.executor, "last_dispatch", [])
        self._pub("automation.actions", id=inc["id"], action=inc["action"], service=inc["root"], tools=[d["tool"] for d in inc["dispatched"]])
        inc.update(status="verifying", verify_streak=0, deadline=self.tick + C.VERIFY_TIMEOUT)
        self._note(f"Executed (attempt {inc['attempts']}): {msg}")
        audit.log("action", id=inc["id"], action=inc["action"], service=inc["root"], detail=msg, attempt=inc["attempts"])

    # ------------------------------------------------------------ verify + learn
    def _advance(self, metrics):
        inc = self.incident
        if inc["status"] != "verifying":
            return  # waiting for a human (pending_approval / escalated)
        healthy, problems = check(metrics, self.detector.baseline)
        inc["verify_streak"] = inc["verify_streak"] + 1 if healthy else 0
        self._pub("verification.results", id=inc["id"], healthy=healthy, streak=inc["verify_streak"])
        if inc["verify_streak"] >= C.VERIFY_STREAK:
            self._resolve()
        elif self.tick > inc["deadline"]:
            self._note("Post-heal check FAILED: " + "; ".join(problems[:3]))
            if inc["attempts"] < C.MAX_ATTEMPTS:
                self._note("Retrying remediation")
                self._decide()
            else:
                inc["status"] = "escalated"
                self._note("Retries exhausted -> escalated to DevOps engineer")
                audit.log("escalated", id=inc["id"], reasons=["recovery verification failed"])
                self._learn(inc, False)

    def _resolve(self, by_human=False):
        inc = self.incident
        inc["status"] = "resolved"
        inc["t_resolved"] = self.tick
        start = inc["t_fault"] if inc["t_fault"] is not None else inc["t_detect"]
        inc["mttr"] = (self.tick - start) * C.TICK_SECONDS
        self._note(f"Recovery verified (health check passed) - incident resolved, MTTR {inc['mttr']:.0f}s")
        if hasattr(self.executor, "reconcile"):
            self._note(self.executor.reconcile(inc["root"]))
        if not by_human:
            self._learn(inc, True)
        self.kb.add(dict(failure_type=inc["failure_type"], service=inc["root"], symptoms=inc["symptoms"],
                         root_cause=f"auto-diagnosed {inc['failure_type']}", action=inc["action"], outcome="resolved"))
        self._note("Incident stored in knowledge base (continuous learning)")
        self._pub("learning.kb", id=inc["id"], kb_size=len(self.kb.items))
        audit.log("resolved", id=inc["id"], mttr=inc["mttr"])
        self._close()

    def _learn(self, inc, ok):
        s = self.policy.record_outcome(inc["failure_type"], inc["action"], ok)
        if s[1] >= 2 and s[0] / s[1] <= 0.5:
            self._note(f"Policy update: '{inc['action']}' for {inc['failure_type']} now {s[0]}/{s[1]} successful -> human approval required next time")
            self._pub("policy.updates", rule=f"{inc['failure_type']}->{inc['action']}", success=f"{s[0]}/{s[1]}")
            audit.log("policy_update", rule=f"{inc['failure_type']}->{inc['action']}", success=f"{s[0]}/{s[1]}")

    def _close(self):
        self._persist()
        self.closed.append(self.incident)
        self.incident = None
        for s in self.services:
            self.consec[s] = 0

    def _persist(self):
        if self.store and self.incident is not None:
            self.store.save_incident(self.incident, self.run)

    def _note(self, msg):
        if self.incident is not None:
            self.incident["timeline"].append(dict(tick=self.tick, msg=msg))
            self._persist()

    # ------------------------------------------------------------ human-in-the-loop API
    def approve(self):
        with self.lock:
            inc = self.incident
            if inc and inc["status"] == "pending_approval":
                self._note("Human APPROVED the action")
                audit.log("human_approval", id=inc["id"], decision="approved")
                self._execute()
                return True
            return False

    def reject(self):
        with self.lock:
            inc = self.incident
            if inc and inc["status"] == "pending_approval":
                inc["status"] = "escalated"
                self._note("Human REJECTED the action -> manual handling")
                audit.log("human_approval", id=inc["id"], decision="rejected")
                return True
            return False

    def acknowledge_escalation(self):
        """Engineer fixed the problem manually and closes the ticket."""
        with self.lock:
            if self.incident and self.incident["status"] == "escalated":
                inc = self.incident
                inc["status"] = "closed_by_human"
                inc["mttr"] = None
                self._note("Closed by DevOps engineer after manual fix")
                audit.log("closed_by_human", id=inc["id"])
                self._close()
                return True
            return False

    def set_auto_approve(self, v):
        self.policy.auto_approve_high_risk = bool(v)

    def whatif(self, service, m):
        base = self.detector.baseline[service]
        score, anom = self.detector.score(service, m)
        proba = self.classifier.proba(m, base)
        label = max(proba, key=proba.get)
        out = dict(service=service, anomaly_score=score, anomalous=anom, proba=proba, label=label,
                   confidence=proba[label], symptoms=symptom_text(service, m, base),
                   kb=self.kb.query(symptom_text(service, m, base), 3), action=None, policy=None)
        if label != "normal":
            action, why = plan(label)
            out.update(action=action, why=why,
                       policy=self.policy.evaluate(self.tick, action, service, label, self._replicas(service)))
        return out

    def models_info(self):
        return dict(isolation_forest=dict(n_estimators=150, contamination=0.01, z_guard=6, baselines=self.detector.baseline,
                                          std=self.detector.std, consecutive=C.CONSECUTIVE_ANOMALIES),
                    random_forest=dict(trees=200, classes=list(self.classifier.model.classes_),
                                       importances=self.classifier.importances()),
                    kb_size=len(self.kb.items), router=self.router.backend)

    def _replicas(self, svc):
        h = self.history[svc]
        return h[-1].get("replicas", 1) if h else 1

    # ------------------------------------------------------------ dashboard snapshot
    def snapshot(self, n=60):
        with self.lock:
            if self.store:   # history survives restarts
                rep = self.store.report(C.MANUAL_MTTR_SECONDS)
                cur = self.incident["id"] if self.incident else None
                closed = [{k: r.get(k) for k in ("id", "root", "failure_type", "action", "status", "mttr", "attempts")}
                          for r in self.store.list_incidents(limit=9) if r["id"] != cur][:8]
                total, resolved_n, avg = rep["total"] - (1 if self.incident else 0), rep["resolved"], rep["avg_mttr"]
            else:
                res = [i for i in self.closed if i["status"] == "resolved" and i.get("mttr") is not None]
                closed = [{k: i.get(k) for k in ("id", "root", "failure_type", "action", "status", "mttr", "attempts")}
                          for i in self.closed[-8:]][::-1]
                total, resolved_n = len(self.closed), len(res)
                avg = round(sum(i["mttr"] for i in res) / len(res), 1) if res else None
            return dict(
                tick=self.tick, mode=getattr(self.collector, "name", "?"), run=self.run, deps=self.deps,
                settings=dict(auto_approve=self.policy.auto_approve_high_risk, paused=self.paused, tick_seconds=self.tick_seconds),
                services={s: dict(latest=(list(self.history[s])[-1] if self.history[s] else None),
                                  series=[{k: h[k] for k in ("tick", "cpu", "mem", "latency", "error_rate", "rps", "score", "anomalous")}
                                          for h in list(self.history[s])[-n:]]) for s in self.services},
                truth=self.collector.ground_truth() if hasattr(self.collector, "ground_truth") else {},
                incident=self.incident,
                closed=closed,
                stats=dict(total=total, resolved=resolved_n, avg_mttr=avg,
                           manual_mttr=C.MANUAL_MTTR_SECONDS, kb_size=len(self.kb.items),
                           action_success=self.policy.success_rates()),
                audit=audit.tail(12)[::-1],
                router=dict(counts=dict(self.router.counts), total=self.router.total, backend=self.router.backend),
                signals=dict(logs=list(self.logs)[-30:][::-1], events=list(self.events_buf)[-12:][::-1], traces=list(self.traces)[-8:][::-1]),
                infra=dict(cluster=("sim-eks-cluster" if getattr(self.collector, "name", "") == "simulation" else "local-process"),
                           nodes={s: f"node-{i % 2 + 1}" for i, s in enumerate(self.services)}),
            )
