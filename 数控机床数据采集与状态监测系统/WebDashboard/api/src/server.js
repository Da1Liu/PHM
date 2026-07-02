import 'dotenv/config';
import express from 'express';
import cors from 'cors';
import { fileURLToPath } from 'url';
import path from 'path';
import * as repo from './repository.js';
import { startPoller, stopPoller, restartPoller, getStatus as opcuaStatus } from './opcua/poller.js';
import { buildOpcua, DERIVED_OPCUA3 } from './opcua/config.js';
import { ensureConfigTable, getConfig, saveConfig, getSignals, EDGE_MACHINE_ID } from './configStore.js';
import { ensureControlTable, getNiStatus, setNiRun, requestCapture } from './niControl.js';
import * as vib from './vibStore.js';
import * as exp from './exportStore.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const app = express();
const PORT = Number(process.env.PORT || 4000);
const MAX_POINTS = Number(process.env.MAX_POINTS || 1000);

app.use(cors());
app.use(express.json());

const wrap = (fn) => (req, res) =>
  Promise.resolve(fn(req, res)).catch((err) => {
    console.error(`[api] ${req.method} ${req.path} ->`, err.message);
    res.status(err.status || 500).json({ error: err.message });
  });

function clampPoints(v) {
  const n = Number(v);
  if (!Number.isFinite(n) || n <= 0) return MAX_POINTS;
  return Math.min(Math.max(Math.floor(n), 10), 5000);
}

function parseList(v) {
  if (!v) return [];
  return String(v).split(',').map((s) => s.trim()).filter(Boolean);
}

let opcuaDesiredSignature = null;
let reconciling = false;

function opcuaSignature(cfg) {
  const desired = !!(cfg.control?.opcua_run ?? cfg.opcua?.enabled);
  if (!desired) return 'off';
  const o = cfg.opcua || {};
  return JSON.stringify({
    endpoint: o.endpoint,
    username: o.username,
    password: o.password,
    anonymous: !!o.anonymous,
    pollIntervalMs: Number(o.pollIntervalMs || 1000),
    profile: o.profile,
  });
}

async function reconcileOpcua() {
  if (reconciling) return;
  reconciling = true;
  try {
    const cfg = await getConfig();
    const sig = opcuaSignature(cfg);
    if (sig === opcuaDesiredSignature) return;
    opcuaDesiredSignature = sig;
    if (sig === 'off') {
      await stopPoller();
    } else {
      await restartPoller({ ...cfg.opcua, enabled: true });
    }
  } catch (err) {
    console.error('[opcua] reconcile failed:', err.message);
  } finally {
    reconciling = false;
  }
}

function valueOfKnownSignal(signal, latestByTable) {
  const code = signal.code;
  if (latestByTable.r2 && Object.prototype.hasOwnProperty.call(latestByTable.r2, code)) {
    return { table: '_OPCUA_2', value: latestByTable.r2[code], latestTime: latestByTable.r2.time };
  }
  if (latestByTable.r3 && Object.prototype.hasOwnProperty.call(latestByTable.r3, code)) {
    return { table: '_OPCUA_3', value: latestByTable.r3[code], latestTime: latestByTable.r3.time };
  }
  if (latestByTable.rnew && Object.prototype.hasOwnProperty.call(latestByTable.rnew, code)) {
    return { table: '_OPCUA_new', value: latestByTable.rnew[code], latestTime: latestByTable.rnew.time };
  }
  return { table: null, value: null, latestTime: null };
}

function groupSignals(signals, latestByTable) {
  const groups = new Map();
  for (const s of signals) {
    const system = s.phm_system || 'unclassified';
    if (!groups.has(system)) groups.set(system, []);
    const live = valueOfKnownSignal(s, latestByTable);
    groups.get(system).push({
      id: s.signal_id,
      code: s.code,
      col: s.code,
      label: s.display_name || s.code,
      node: s.source_addr || '',
      type: s.signal_kind || '',
      protocol: s.protocol,
      unit: s.unit,
      highFreq: !!s.is_high_freq,
      filed: true,
      table: live.table,
      value: live.value,
      latestTime: live.latestTime,
    });
  }
  return [...groups.entries()].map(([system, rows]) => ({
    table: 'phm_v2.signal',
    title: system,
    latestTime: rows.map((r) => r.latestTime).filter(Boolean).sort().at(-1) || null,
    signals: rows,
  }));
}

app.get('/api/health', wrap(async (req, res) => {
  await repo.ping();
  res.json({ status: 'ok', db: process.env.PGDATABASE || 'vibration_db', machineId: EDGE_MACHINE_ID });
}));

app.get('/api/tables', wrap(async (req, res) => {
  res.json(await repo.listTables());
}));

app.get('/api/opcua/status', wrap(async (req, res) => {
  res.json(opcuaStatus());
}));

app.get('/api/opcua/catalog', wrap(async (req, res) => {
  const cfg = await getConfig();
  const st = opcuaStatus();
  const [r2, r3, rnew] = await Promise.all([
    repo.getLatestRow('_OPCUA_2'),
    repo.getLatestRow('_OPCUA_3'),
    repo.getLatestRow('_OPCUA_new'),
  ]);

  let signalRows = [];
  try {
    signalRows = await getSignals();
  } catch (err) {
    console.warn('[signal] catalog unavailable:', err.message);
  }

  const groups = signalRows.length
    ? groupSignals(signalRows, { r2, r3, rnew })
    : [{ table: 'phm_v2.signal', title: '未建档', latestTime: null, signals: [] }];

  const maps = buildOpcua(cfg.opcua.profile);
  res.json({
    machineId: EDGE_MACHINE_ID,
    profile: cfg.opcua.profile,
    endpoint: cfg.opcua.endpoint,
    pollIntervalMs: cfg.opcua.pollIntervalMs,
    enabled: !!(cfg.control?.opcua_run ?? cfg.opcua.enabled),
    status: { running: st.running, connected: st.connected, lastError: st.lastError, lastOkAt: st.lastOkAt },
    nodeCount: maps.allNodeIds.length,
    source: signalRows.length ? 'phm_v2.signal' : 'unfiled',
    groups,
    legacyMaps: {
      opcua2: maps.OPCUA2_MAP.length,
      opcua3: maps.OPCUA3_MAP.length + DERIVED_OPCUA3.length,
      coords: maps.OPCUA_NEW_MAP.length,
    },
  });
}));

app.get('/api/signals/catalog', wrap(async (req, res) => {
  let rows = [];
  try { rows = await getSignals(); } catch { rows = []; }
  res.json({ machineId: EDGE_MACHINE_ID, source: rows.length ? 'phm_v2.signal' : 'unfiled', signals: rows });
}));

app.post('/api/opcua/start', wrap(async (req, res) => {
  await saveConfig({ opcua: { enabled: true }, control: { opcua_run: true } });
  await reconcileOpcua();
  res.json({ ok: true, opcua: opcuaStatus() });
}));
app.post('/api/opcua/stop', wrap(async (req, res) => {
  await saveConfig({ opcua: { enabled: false }, control: { opcua_run: false } });
  await reconcileOpcua();
  res.json({ ok: true, opcua: opcuaStatus() });
}));

app.get('/api/ni/status', wrap(async (req, res) => {
  res.json(await getNiStatus());
}));
app.post('/api/ni/start', wrap(async (req, res) => {
  res.json({ ok: true, ni: await setNiRun(true) });
}));
app.post('/api/ni/stop', wrap(async (req, res) => {
  res.json({ ok: true, ni: await setNiRun(false) });
}));
app.post('/api/ni/capture', wrap(async (req, res) => {
  const seq = await requestCapture();
  res.json({ ok: true, capture_seq: seq });
}));

app.get('/api/vib/sessions', wrap(async (req, res) => {
  res.json(await vib.listSessions({ limit: req.query.limit }));
}));
app.get('/api/vib/features', wrap(async (req, res) => {
  res.json(await vib.getFeatures({
    channels: parseList(req.query.channels).map(Number),
    from: req.query.from,
    to: req.query.to,
    maxPoints: clampPoints(req.query.maxPoints),
  }));
}));
app.get('/api/vib/events', wrap(async (req, res) => {
  res.json(await vib.listEvents({ limit: req.query.limit }));
}));
app.get('/api/vib/block', wrap(async (req, res) => {
  const eventId = req.query.event;
  if (!eventId) return res.status(400).json({ error: 'missing event parameter' });
  res.json(await vib.getEventBlocks({ eventId, maxPoints: clampPoints(req.query.maxPoints) }));
}));

function sendCsv(res, filename, csv) {
  res.setHeader('Content-Type', 'text/csv; charset=utf-8');
  res.setHeader('Content-Disposition', `attachment; filename*=UTF-8''${encodeURIComponent(filename)}`);
  res.send(csv);
}
app.get('/api/export/vib/block', wrap(async (req, res) => {
  if (!req.query.event) return res.status(400).json({ error: 'missing event parameter' });
  const { filename, csv } = await exp.buildRawBlockCsv(req.query.event);
  sendCsv(res, filename, csv);
}));
app.get('/api/export/vib/features', wrap(async (req, res) => {
  const { filename, csv } = await exp.buildFeaturesCsv({
    from: req.query.from, to: req.query.to,
    channels: parseList(req.query.channels).map(Number),
  });
  sendCsv(res, filename, csv);
}));
app.get('/api/export/opcua', wrap(async (req, res) => {
  const { filename, csv } = await exp.buildOpcuaCsv({
    key: req.query.table, from: req.query.from, to: req.query.to,
    maxPoints: Number(req.query.maxPoints) || 0,
  });
  sendCsv(res, filename, csv);
}));

app.get('/api/config', wrap(async (req, res) => {
  res.json(await getConfig());
}));

app.put('/api/config', wrap(async (req, res) => {
  const next = await saveConfig(req.body || {});
  await reconcileOpcua();
  res.json({ saved: true, config: next, opcua: opcuaStatus() });
}));

app.get('/api/spindle/trend', wrap(async (req, res) => {
  res.json(await repo.getSpindleTrend({ from: req.query.from, to: req.query.to, maxPoints: clampPoints(req.query.maxPoints) }));
}));

app.get('/api/axes/trend', wrap(async (req, res) => {
  res.json(await repo.getAxesTrend({
    axes: parseList(req.query.axes),
    metric: req.query.metric || 'current',
    from: req.query.from,
    to: req.query.to,
    maxPoints: clampPoints(req.query.maxPoints),
  }));
}));

app.get('/api/coordinates', wrap(async (req, res) => {
  res.json(await repo.getCoordinates({ from: req.query.from, to: req.query.to, maxPoints: clampPoints(req.query.maxPoints) }));
}));

app.get('/api/vibration/range', wrap(async (req, res) => {
  const table = req.query.table;
  if (!table) return res.status(400).json({ error: 'missing table parameter' });
  res.json(await repo.getIdRange(table));
}));

app.get('/api/vibration', wrap(async (req, res) => {
  const table = req.query.table;
  if (!table) return res.status(400).json({ error: 'missing table parameter' });
  res.json(await repo.getVibration({
    table,
    channels: parseList(req.query.channels).map(Number),
    start: req.query.start != null ? Number(req.query.start) : null,
    end: req.query.end != null ? Number(req.query.end) : null,
    maxPoints: clampPoints(req.query.maxPoints),
  }));
}));

app.use('/', express.static(path.join(__dirname, '..', '..', 'web')));

app.listen(PORT, async () => {
  console.log(`dashboard/acquisition backend started: http://localhost:${PORT}`);
  console.log(`db: ${process.env.PGDATABASE || 'vibration_db'} @ ${process.env.PGHOST || 'localhost'}:${process.env.PGPORT || 5432}`);
  console.log(`edge machine: ${EDGE_MACHINE_ID}`);

  try {
    await ensureConfigTable();
    await ensureControlTable();
    await reconcileOpcua();
    setInterval(reconcileOpcua, 1000).unref();
  } catch (err) {
    console.error('[config] initialization failed:', err.message);
  }
});

async function shutdown() {
  console.log('\nshutting down...');
  await stopPoller();
  process.exit(0);
}
process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);

