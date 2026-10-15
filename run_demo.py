"""Headless terminal demo - no browser, no Docker, no Node needed.
   python run_demo.py            (runs 5 scripted failure scenarios)
"""
import sys, time
from selfheal import config as C
from selfheal.simulator import Simulator, SimExecutor
from selfheal.engine import Engine
from selfheal.automation import AutomationRouter

G, Y, R, B, X = "\033[92m", "\033[93m", "\033[91m", "\033[94m", "\033[0m"


def run_scenario(eng, sim, title, service, fault, stubborn=False, max_ticks=120):
    print(f"\n{B}=== {title} ==={X}")
    for _ in range(10):  # let the system settle
        eng.step()
    n_closed = len(eng.closed)
    print(sim.inject(service, fault, stubborn), "(hidden from the AI)")
    cur, seen, approved = None, 0, False
    for _ in range(max_ticks):
        eng.step()
        if cur is None and eng.incident is not None:
            cur = eng.incident
        if cur is None:
            continue
        for e in cur["timeline"][seen:]:
            print(f"  [t={e['tick']:>3}] {e['msg']}")
        seen = len(cur["timeline"])
        if cur["status"] == "pending_approval" and not approved:
            print(f"  {Y}>> human clicks APPROVE{X}"); eng.approve(); approved = True
        elif cur["status"] == "escalated":
            print(f"  {R}>> engineer fixes manually and closes ticket{X}")
            sim.clear_all(); eng.acknowledge_escalation()
            for e in cur["timeline"][seen:]: print(f"  [t={e['tick']:>3}] {e['msg']}")
            break
        elif cur["status"] == "resolved":
            print(f"  {G}MTTR = {cur['mttr']:.0f}s{X}")
            break
    if cur: print("  Explanation:", cur["explanation"])
    else: print(f"  {R}No incident detected!{X}")
    for _ in range(5): eng.step()


def main():
    sim = Simulator(seed=42)
    eng = Engine(sim, AutomationRouter(SimExecutor(sim)), C.SERVICES, C.DEPENDENCIES, auto_approve=False)
    print("Training Isolation Forest on healthy baseline ...")
    eng.warmup()
    run_scenario(eng, sim, "1. API container crash", "api", "container_crash")
    run_scenario(eng, sim, "2. Memory leak in auth service", "auth", "memory_exhaustion")
    run_scenario(eng, sim, "3. CPU overload on API (traffic spike)", "api", "cpu_overload")
    run_scenario(eng, sim, "4. Bad deployment on frontend", "frontend", "bad_deployment")
    run_scenario(eng, sim, "5. Database failure (cascades to api + frontend, high-risk -> approval)", "database", "database_failure")
    run_scenario(eng, sim, "6. Stubborn failure the AI cannot fix -> escalation", "api", "container_crash", stubborn=True)
    s = eng.snapshot()["stats"]
    print(f"\n{G}Summary:{X} {s['resolved']}/{s['total']} incidents closed. Avg auto-MTTR {s['avg_mttr']}s vs assumed manual {s['manual_mttr']}s. KB size: {s['kb_size']}")
    print("Action success:", s["action_success"])
    print("Audit log written to data/audit_log.jsonl")

if __name__ == "__main__":
    main()
