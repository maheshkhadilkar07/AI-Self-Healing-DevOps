# AI Self-Healing DevOps

Working prototype of the framework in the project presentation:
**Monitor -> Detect -> Decide -> Heal -> Verify -> Learn**

### Block diagram -> code (what is real vs. stand-in)

| Block in your diagram | Implementation | Status |
|---|---|---|
| Target infrastructure (K8s/EKS, nodes, pods, MERN app) | `simulator.py` (4 services on 2 nodes, pods = replicas), `demo-app/` (Express app), `deploy/k8s/deployment.yaml` | Simulated / local; K8s YAML provided, not applied by the demo |
| A. Observability: Metrics, Logs, Traces, Events | `simulator.py`/`collectors.py` emit all four; app exposes Prometheus `/metrics`; `deploy/prometheus.yml` | Real signals from sim + live app; engine reads the app directly (not via a Prometheus server) |
| Kafka Event Router | `events.py` - topic-based router; all telemetry and decisions flow through it. Optional real Kafka mirror via `KAFKA_BOOTSTRAP` | In-process by default; Kafka mirror untested against a live broker |
| B. Anomaly detection (Isolation Forest) | `anomaly.py` (+ z-score guard) | Real |
| B. Contextual RCA (LLM + RAG) | `rca.py` (dependency graph + correlation), `knowledge_base.py` (cosine retrieval), `explain.py` (LLM if API key, else template) | Retrieval real; LLM optional |
| B. Incident knowledge base | `data/incident_kb.json`, grows on every resolved incident | Real |
| C. ArgoCD (GitOps reconciliation) | `deploy/k8s/argocd-app.yaml`; `automation.py` adds an ArgoCD sync/reconcile step to every plan | Dry-run dispatch |
| C. Policy and risk engine | `policy.py` (allowlist, playbook check, risk, human approval, flapping guard, **learned restriction from past success rate**) | Real |
| C. Automated remediation plan | `remediation.py` + `automation.py` (ordered tool steps shown in the dashboard) | Real |
| C. Ansible Automation Controller | `automation/ansible/*.yml` (restart, scale) | Playbooks included; dispatch is dry-run (logged + audited) |
| C. GitHub Actions | `.github/workflows/rollback.yml` (GitOps revert) | Template included; dispatch is dry-run |
| D. Health check -> Recovered? | `verifier.py`; Yes = resolved, No = retry, then escalate | Real |
| Retry/Escalate -> DevOps engineer | `engine.py` + dashboard "Engineer fixed it" button | Real |
| Continuous learning / policy update (feedback loop) | KB growth + success-rate tracking that changes approval rules (`policy.updates` topic) | Real (rule updates; models are not retrained) |

## 1. What to install

| Needed for | Install |
|---|---|
| Everything (required) | **Python 3.9+** (https://www.python.org/downloads/, tick "Add to PATH" on Windows) |
| Live mode only (optional) | **Node.js 18+** (https://nodejs.org) |
| Containers (optional, not needed for demo) | Docker Desktop; kubectl + a cluster (minikube/EKS) |

## 2. Setup (once, needs internet)

```bash
cd ai-self-healing-devops
python -m venv venv
# Windows:  venv\Scripts\activate        Mac/Linux:  source venv/bin/activate
pip install -r requirements.txt
```
(On Mac/Linux use `python3` if `python` is not found.)

## 3. Run

**A. Terminal demo (fastest check, 10 seconds):**
```bash
python run_demo.py
```
Runs 6 scenarios: crash, memory leak, CPU overload, bad deployment, DB failure (needs human approval), and an unfixable failure that escalates.

**B. Web application - simulation mode (best for the seminar):**
```bash
python run_dashboard.py
```
Open http://127.0.0.1:5000 - a multi-page site (16 pages). Everything is stored in `data/history.db`, so incidents, metrics, logs and reports **survive restarts**.

| Group | Page | What you can do there |
|---|---|---|
| Project | `/` Home | Project intro, live status strip, clickable system flow |
| | `/project` | Abstract, introduction, objectives, team, conclusion |
| | `/literature` | 10-paper literature survey with search filter and research gap |
| | `/methodology` | The six algorithms, code location, "try it" links, real-vs-stand-in table |
| | `/references` | All 16 references |
| Live system | `/overview` | KPIs (MTTR, MTTD, availability), service health cards, active incident, approve/reject |
| | `/monitor` | Interactive charts: pick metric, services, time window, hover values, freeze |
| | `/architecture` | Live block diagram, dependency graph (root cause highlighted), event-router topics |
| | `/incidents` | Searchable/filterable history, click any row for the full investigation, CSV/JSON export |
| | `/chaos` | One-click scenarios (crash, DB outage, memory leak, bad release, traffic spike, double fault, unfixable) or custom failures |
| | `/ai` | Isolation Forest score chart, Random Forest probabilities + feature importance, **what-if analyzer** (drag sliders), knowledge-base search |
| Operations | `/policy` | Approval queue, risk rules, learned success rates, guard rails |
| | `/logs` | Stored logs / K8s events (search, filter) and live traces |
| | `/audit` | Searchable audit trail of every decision and action |
| | `/reports` | MTTR chart, breakdowns, availability, printable (Save as PDF) |
| | `/settings` | Auto-approve, pause, tick speed, theme, clear history |

**C. Web dashboard - LIVE mode (real Node app, real crash/restart):**
```bash
python run_dashboard.py --mode live
```
Needs Node.js. The first run does `npm install` automatically. The target app is at http://127.0.0.1:3000 - open it in another tab and watch it die and come back.
Add `--auto-approve` to skip human approval for high-risk actions.

The **Architecture** page mirrors your block diagram and lights up as the incident moves through each layer.

**D. Optional - containers / Kubernetes:** `docker compose -f deploy/docker-compose.yml up --build` (app + Prometheus), or `kubectl apply -f deploy/k8s/deployment.yaml`.

## 4. Optional LLM explanations
`pip install anthropic`, then set `ANTHROPIC_API_KEY` (and optionally `LLM_MODEL`). Without a key the explanation is template-generated; everything else is unchanged.

## 5. Honest scope notes (say these if asked)
- **Ansible / GitHub Actions / ArgoCD:** the playbooks, workflow and Application manifest are included and each action is dispatched (logged and audited) as a dry-run; actually calling them needs Ansible, a GitHub token and an ArgoCD server.
- **Simulation mode** generates metrics and applies fixes inside a simulator. **Live mode** uses a real process; `restart` and `rollback` are real process restarts, while `scale` is emulated (one local process) - these stand in for `kubectl rollout restart`, `argocd app rollback`, `kubectl scale`. Replacing the executors with real kubectl/Ansible/ArgoCD calls is the production step.
- The failure classifier is trained on synthetic symptom profiles; production use needs labelled historical incidents.
- Anomaly detection = Isolation Forest **plus a z-score guard** (Isolation Forest alone cannot measure how far a value is outside its training range).
- "Manual MTTR 15 min" on the dashboard is an **assumed** figure for comparison, not a measurement. MTTR in the simulator is counted in monitoring ticks (1 tick = 1 s).

## 6. Troubleshooting
- `ModuleNotFoundError` -> activate the venv and run `pip install -r requirements.txt`.
- Port 5000 busy (macOS AirPlay) -> `python run_dashboard.py --port 5050`.
- Live mode: "Node.js not found" -> install Node 18+ or use simulation mode.
- Reset everything: stop the app and delete `data/history.db*`, `data/incident_kb.json`, `data/audit_log.jsonl` (or use Settings -> Clear stored history).
