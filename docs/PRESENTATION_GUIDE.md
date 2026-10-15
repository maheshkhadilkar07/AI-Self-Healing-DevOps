# Seminar guide - AI Self-Healing DevOps

## 0. Fix these in your PPT before presenting
- **Slide 6 (Methodology)** still has drafting notes: "This should be your primary ML algorithm", "Useful with RAG", "your incident knowledge base". Delete or reword them.
- Block diagram: "KBS/EKS" -> **K8s/EKS**; "Deploy Chotter Fixes" -> **Deploy Faster Fixes** (or similar); "Continuos" -> **Continuous**; "Reconcilation" -> **Reconciliation**; "Github" -> **GitHub**.
- Title slide: "Swati Chaudhary (221" is missing a closing bracket.
- Introduction: "failures  to increased downtime" is missing a verb ("lead to"); "verifies system recover" -> "recovery".
- Reference [12]: page range "27162721" -> "2716-2721".

## 1a. Page-by-page route for the presentation
`/` (Home: say the one-line pitch) -> `/project` (abstract) -> `/literature` (research gap) -> `/methodology` (six techniques) -> `/architecture` (block diagram) -> **live demo** (`/chaos` scenario, watch `/overview`, open the incident in `/incidents`, show `/ai` what-if, `/policy` approval, `/reports`) -> conclusion.

## 1. Suggested 8-10 minute flow
1. **Problem (1 min)** - manual detection/diagnosis/recovery => downtime, high MTTR.
2. **Solution + architecture (2 min)** - walk the block diagram left to right: Observability -> AI core -> Decision & Automation -> Verification -> feedback loop.
3. **Techniques (2 min)** - one sentence per algorithm (see table below).
4. **LIVE DEMO (3 min)** - `python run_dashboard.py`:
   a. Inject **Container crash** on `api` -> show detect, root cause, restart, verified, MTTR.
   b. Inject **Database failure** -> show cascade (api, frontend also red), root cause = database, **approval gate**, click Approve.
   c. Inject **stubborn** crash -> retries fail -> escalation to engineer (shows safety).
   d. Point at the Knowledge-base counter growing (continuous learning) and the audit log.
5. **Conclusion (1 min)** - lower MTTR, less manual work, safe automation via policy + verification.

## 2. Slide -> code map
| Slide item | What it does here | File |
|---|---|---|
| Isolation Forest | Learns healthy CPU/mem/latency/error/throughput per service; flags outliers | `selfheal/anomaly.py` |
| Random Forest | Classifies failure type (crash, memory, CPU, bad deploy, DB) | `selfheal/classifier.py` |
| Correlation + dependency graph | Finds the *origin* service when failures cascade | `selfheal/rca.py` |
| Cosine similarity (RAG retrieval) | Finds similar past incidents (TF-IDF vectors) | `selfheal/knowledge_base.py` |
| Rule-based remediation | crash -> restart, load -> scale, bad deploy -> rollback | `selfheal/remediation.py` |
| Policy & risk engine | Allowlist, playbook check, risk level, human approval, flapping guard | `selfheal/policy.py` |
| Threshold health check | N consecutive healthy ticks => resolved, else retry/escalate | `selfheal/verifier.py` |
| Audit logging | Every diagnosis, policy decision, action in JSON lines | `selfheal/audit.py`, `data/audit_log.jsonl` |

## 2b. Walking the block diagram during the demo
The dashboard has a **Block diagram - live** panel. While an incident runs, point left to right:
1. **Target infra** - which node/pods the service runs on.
2. **A. Observability** - metric/log/trace/event counters rise; error logs and K8s events appear (e.g. "process exited with code 137", "BackOff").
3. **Event router + B. AI core** - Isolation Forest flags the service, RCA names the root, Random Forest gives the failure type, KB shows the similar past incident.
4. **C. Decision & automation** - policy decision, then the plan: Ansible (or GitHub Actions for rollback) followed by ArgoCD reconcile.
5. **D. Verification** - health-check streak; resolved, or retry then escalate to the engineer.
6. **Feedback loop** - KB count increases; after repeated failures a *policy update* makes that action need human approval.

## 3. Likely questions - short answers
- **Why Isolation Forest?** Unsupervised: needs only healthy data, no labelled failures; fast; handles multi-metric outliers.
- **Why not just Kubernetes liveness probes / HPA?** They fix one symptom with fixed rules. Ours detects anomalies beyond crashes, finds root cause across dependent services, chooses among actions, verifies recovery, and learns.
- **What stops the AI doing something dangerous?** Policy engine: action allowlist, must match validated playbook, risk scoring, replica cap, flapping guard, human approval for high-risk (DB restart), audit log, escalation after failed retries.
- **Where is the LLM+RAG?** Retrieval is implemented (TF-IDF cosine over the incident KB). The LLM explanation step is optional via an API key; otherwise a template is used. Say this plainly.
- **Do Ansible / GitHub Actions / ArgoCD really run?** The playbooks, workflow and manifest are in the repo and every action is dispatched through them as a logged dry-run; the effect is applied to the simulator / demo app. Calling the real tools is the next integration step.
- **Is Kafka used?** An in-process topic router with the same publish/subscribe design; it can mirror to a real Kafka broker via `KAFKA_BOOTSTRAP` (not tested against a live broker).
- **Is it tested on real production data?** No - simulated and a live demo app. Future work: real Prometheus feed, kubectl/Ansible executors, labelled incident data.
- **How do you measure MTTR?** Time from fault start to verified recovery. The 15-min manual figure is an assumption from typical on-call response, not measured.
- **False positives?** Action only after 3 consecutive anomalous ticks, the classifier must confirm a real failure type, and verification must pass.
- **What does RBAC / secrets management mean in your abstract?** Design-level: the executor would use a least-privilege Kubernetes ServiceAccount and secrets from a vault; the prototype enforces the action allowlist and approval gate.

## 4. Demo-day checklist
- [ ] Install + `python run_demo.py` works on the laptop you will present from (do it tonight, with internet for `pip`).
- [ ] Run the dashboard once; delete `data/incident_kb.json` and `data/audit_log.jsonl` for a clean start.
- [ ] Have a screen-recording / screenshots as backup in case of projector or laptop problems.
- [ ] Decide who presents what; every member should be able to explain one module.
