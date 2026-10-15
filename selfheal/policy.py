"""Policy & risk engine - validates every AI-proposed action before execution (RBAC-style allowlist,
risk scoring, blast-radius limits, human approval for high-risk actions)."""
from .config import MAX_REPLICAS
from .remediation import RULES

ALLOWED_ACTIONS = {"restart", "scale", "rollback"}


class PolicyEngine:
    def __init__(self, auto_approve_high_risk=False):
        self.auto_approve_high_risk = auto_approve_high_risk
        self.recent = []  # (tick, service, action)
        self.stats = {}   # (failure_type, action) -> [successes, attempts]  (policy learning)

    def risk(self, action, service):
        if action == "restart" and service == "database":
            return "high"           # stateful service - restart may drop connections
        if action == "rollback":
            return "medium"
        return "low"

    def evaluate(self, tick, action, service, failure_type, replicas=1):
        reasons = []
        if action not in ALLOWED_ACTIONS:
            return dict(decision="denied", risk="high", reasons=[f"action '{action}' not in allowlist"])
        expected = RULES.get(failure_type, (None,))[0]
        if action != expected:
            return dict(decision="denied", risk="high",
                        reasons=[f"AI-proposed '{action}' does not match validated playbook for {failure_type}"])
        if action == "scale" and replicas >= MAX_REPLICAS:
            return dict(decision="denied", risk="medium", reasons=[f"replica cap ({MAX_REPLICAS}) reached"])
        flaps = [r for r in self.recent if r[1] == service and tick - r[0] < 120]
        if len(flaps) >= 4:
            return dict(decision="denied", risk="high", reasons=["flapping: too many recent actions on this service"])
        risk = self.risk(action, service)
        reasons.append(f"action '{action}' is in allowlist and matches playbook")
        reasons.append(f"risk level: {risk}")
        st = self.stats.get((failure_type, action))
        learned = bool(st and st[1] >= 2 and st[0] / st[1] <= 0.5)
        if learned:
            reasons.append(f"LEARNED POLICY: '{action}' for {failure_type} succeeded only {st[0]}/{st[1]} times -> human approval required")
        if (risk == "high" and not self.auto_approve_high_risk) or learned:
            return dict(decision="needs_approval", risk="high" if risk == "high" else "learned", reasons=reasons + (["high risk -> human approval required"] if risk == "high" else []))
        return dict(decision="approved", risk=risk, reasons=reasons)

    def record_action(self, tick, service, action):
        self.recent.append((tick, service, action))

    def record_outcome(self, failure_type, action, success):
        s = self.stats.setdefault((failure_type, action), [0, 0])
        s[1] += 1
        s[0] += int(success)
        return s

    def success_rates(self):
        return {f"{f}->{a}": f"{s}/{n}" for (f, a), (s, n) in self.stats.items()}
