"""Technique 5 - Rule-based remediation selection (failure type -> safe action)."""

RULES = {
    "container_crash":   ("restart",  "Container crash -> restart the workload"),
    "memory_exhaustion": ("restart",  "Memory exhaustion / leak -> restart to reclaim memory"),
    "cpu_overload":      ("scale",    "High load -> scale out (add replica)"),
    "bad_deployment":    ("rollback", "Bad deployment -> GitOps rollback to last good revision"),
    "database_failure":  ("restart",  "Database failure -> restart database (needs approval)"),
}


def plan(failure_type):
    return RULES.get(failure_type)
