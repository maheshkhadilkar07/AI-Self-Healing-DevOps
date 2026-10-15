// Target application for the self-healing demo (stand-in for the MERN app in the project).
// Express API + static frontend, Prometheus-style metrics and *chaos endpoints* to inject real failures.
const express = require('express');
const path = require('path');
const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const PORT = process.env.PORT || 3000;
const VERSION = process.env.APP_VERSION || 'v2.0-bad-capable';
const MEM_CAP_MB = 512;

let items = [{ id: 1, text: 'Welcome to the self-healing demo app' }];
let chaos = { badDeploy: false, replicas: 1 };
let leak = [], leakTimer = null, burnTimer = null;
let reqCount = 0, errCount = 0, latSum = 0;

// ---- API
app.get('/health', (req, res) => res.json({ status: 'ok', version: VERSION }));
app.get('/api/items', (req, res) => {
  reqCount++;
  if (chaos.badDeploy && Math.random() < 0.45) { errCount++; return res.status(500).json({ error: 'regression in ' + VERSION }); }
  res.json(items);
});
app.post('/api/items', (req, res) => {
  items.push({ id: Date.now(), text: String(req.body.text || '').slice(0, 200) });
  res.status(201).json(items);
});

// ---- metrics (JSON for the engine, text for Prometheus)
let lastCpu = process.cpuUsage(), lastT = Date.now(), cpuPct = 0;
setInterval(() => {
  const now = Date.now(), c = process.cpuUsage(lastCpu);
  cpuPct = Math.min(100, ((c.user + c.system) / 1000) / (now - lastT) * 100);
  lastCpu = process.cpuUsage(); lastT = now;
}, 1000);
const memPct = () => Math.min(100, process.memoryUsage().rss / 1048576 / MEM_CAP_MB * 100);
app.get('/metrics.json', (req, res) => res.json({ cpu: cpuPct, mem: memPct(), version: VERSION, replicas: chaos.replicas }));
app.get('/metrics', (req, res) => {
  res.type('text/plain').send(
    `# TYPE app_cpu_percent gauge\napp_cpu_percent ${cpuPct.toFixed(1)}\n` +
    `# TYPE app_memory_percent gauge\napp_memory_percent ${memPct().toFixed(1)}\n` +
    `# TYPE app_requests_total counter\napp_requests_total ${reqCount}\n` +
    `# TYPE app_errors_total counter\napp_errors_total ${errCount}\n`);
});

// ---- chaos endpoints (REAL failures inside this process)
app.post('/chaos/cpu', (req, res) => {           // busy-loop blocks the event loop -> CPU + latency spike
  if (burnTimer) clearInterval(burnTimer);
  burnTimer = setInterval(() => {
    const ms = 700 / Math.pow(chaos.replicas, 3); const end = Date.now() + ms; while (Date.now() < end) {}
  }, 1000);
  res.json({ injected: 'cpu_overload' });
});
app.post('/chaos/memory', (req, res) => {        // real memory leak (touches pages so RSS grows)
  if (leakTimer) clearInterval(leakTimer);
  leakTimer = setInterval(() => { if (memPct() < 92) leak.push(Buffer.alloc(8 * 1024 * 1024, 1)); }, 100);
  res.json({ injected: 'memory_exhaustion' });
});
app.post('/chaos/bad-deploy', (req, res) => { chaos.badDeploy = true; res.json({ injected: 'bad_deployment' }); });
app.post('/chaos/crash', (req, res) => { res.json({ injected: 'container_crash' }); setTimeout(() => process.exit(1), 100); });
app.post('/admin/scale', (req, res) => {          // emulated scale-out: load is spread over more "replicas"
  chaos.replicas = Math.max(1, Math.min(5, +req.body.replicas || 1));
  if (chaos.replicas >= 2 && burnTimer) { clearInterval(burnTimer); burnTimer = null; }
  res.json({ replicas: chaos.replicas });
});

// A rolled-back version has no bad code path
if (VERSION.includes('stable')) chaos.badDeploy = false;

app.listen(PORT, () => console.log(`demo app ${VERSION} listening on :${PORT}`));
