"""Central configuration for the AI Self-Healing DevOps framework."""
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA_DIR = BASE / "data"
DATA_DIR.mkdir(exist_ok=True)
KB_PATH = DATA_DIR / "incident_kb.json"
KB_SEED_PATH = DATA_DIR / "incident_kb_seed.json"
AUDIT_PATH = DATA_DIR / "audit_log.jsonl"

# Simulated microservice topology (MERN-style app)
SERVICES = ["frontend", "api", "auth", "database"]
# service -> services it depends on
DEPENDENCIES = {
    "frontend": ["api"],
    "api": ["auth", "database"],
    "auth": [],
    "database": [],
}

TICK_SECONDS = 1.0          # 1 tick = 1 monitoring cycle
WARMUP_TICKS = 60           # healthy samples used to train Isolation Forest
CONSECUTIVE_ANOMALIES = 3   # anomalous ticks in a row before we act (avoids flapping)
VERIFY_STREAK = 3           # healthy ticks in a row needed to declare recovery
VERIFY_TIMEOUT = 14         # ticks to wait for recovery after an action
MAX_ATTEMPTS = 2            # remediation attempts before escalating to a human
MANUAL_MTTR_SECONDS = 900   # ASSUMED manual MTTR (15 min) used only for comparison on dashboard
MAX_REPLICAS = 5
