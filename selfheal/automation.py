"""Decision & Automation layer tooling (block diagram C):
   Automated Remediation Plan -> Ansible Automation Controller / GitHub Actions, with ArgoCD (GitOps) reconciliation.

Each action is turned into an ordered plan of tool dispatches. The dispatch is recorded and audited; the
*effect* is applied through the wrapped executor (simulator or live demo app). Running the real tools needs
Ansible / a GitHub token / an ArgoCD server, so here the artifacts are validated (file must exist) and the
exact command is logged (dry-run) - the production step is replacing `_dispatch` with a subprocess/API call.
"""
from pathlib import Path
from . import audit

ROOT = Path(__file__).resolve().parent.parent

PLAYBOOKS = {
    "restart": ("Ansible Automation Controller", "automation/ansible/restart_workload.yml",
                "ansible-playbook automation/ansible/restart_workload.yml -e service={svc}"),
    "scale": ("Ansible Automation Controller", "automation/ansible/scale_workload.yml",
              "ansible-playbook automation/ansible/scale_workload.yml -e service={svc} -e replicas=+1"),
    "rollback": ("GitHub Actions", ".github/workflows/rollback.yml",
                 "gh workflow run rollback.yml -f service={svc}   # git revert last release"),
}
ARGOCD = ("ArgoCD (GitOps reconciliation)", "deploy/k8s/argocd-app.yaml",
          "argocd app sync demo-app   # make live state match Git")


class AutomationRouter:
    def __init__(self, executor):
        self.executor = executor
        self.last_dispatch = []

    def describe(self, action, service):
        steps = []
        for tool, artifact, cmd in [PLAYBOOKS.get(action), ARGOCD]:
            if tool is None: continue
            steps.append(dict(tool=tool, artifact=artifact, exists=(ROOT / artifact).exists(),
                              command=cmd.format(svc=service)))
        return steps

    def execute(self, action, service, **kw):
        steps = self.describe(action, service)
        for s in steps:
            audit.log("dispatch", tool=s["tool"], artifact=s["artifact"], command=s["command"], dry_run=True)
        self.last_dispatch = steps
        ok, msg = self.executor.execute(action, service, **kw)
        return ok, f"{steps[0]['tool']} -> {steps[0]['command']}  |  then {steps[-1]['tool']}  [effect: {msg}]"

    def reconcile(self, service):
        return "ArgoCD: application 'demo-app' is Synced & Healthy (live state == Git desired state)"
