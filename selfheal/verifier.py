"""Technique 6 - Threshold / health-check recovery verification."""


def check(metrics, baselines):
    """Return (healthy, list_of_problems). Applied to every service."""
    problems = []
    for s, m in metrics.items():
        b = baselines[s]
        if m["cpu"] > 80: problems.append(f"{s}: cpu {m['cpu']}%")
        if m["mem"] > 80: problems.append(f"{s}: mem {m['mem']}%")
        if m["error_rate"] > 5: problems.append(f"{s}: errors {m['error_rate']}%")
        if m["latency"] > 2 * b["latency"]: problems.append(f"{s}: latency {m['latency']}ms")
        if m["rps"] < 0.5 * b["rps"]: problems.append(f"{s}: throughput {m['rps']}")
    return (not problems), problems
