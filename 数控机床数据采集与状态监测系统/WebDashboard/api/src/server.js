import 'dotenv/config';
import express from 'express';
import cors from 'cors';
import { fileURLToPath } from 'url';
import path from 'path';
import * as repo from './repository.js';
import { startPoller, stopPoller, restartPoller, getStatus as opcuaStatus } from './opcua/poller.js';
import { buildOpcua, DERIVED_OPCUA3 } from './opcua/config.js';
import { ensureConfigTable, getConfig, saveConfig, getSignals, updateSignal, saveOpcuaSelection, EDGE_MACHINE_ID, normalizeMachineId } from './configStore.js';
import { ensureControlTable, getNiStatus, setNiRun, requestCapture } from './niControl.js';
import * as vib from './vibStore.js';
import * as exp from './exportStore.js';
import { ApiDomain } from './domain/boundary.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const app = express();
const PORT = Number(process.env.PORT || 4000);
const MAX_POINTS = Number(process.env.MAX_POINTS || 1000);
const WEB_ROOT = path.join(__dirname, '..', '..', 'web');

// API domain inventory for the Edge service. The handlers below keep their
// existing behavior; this table makes placement of future endpoints explicit.
export const API_DOMAINS = Object.freeze([
  { method: 'GET', path: '/api/health', domain: ApiDomain.SHARED, purpose: 'service health and default machine identity' },
  { method: 'GET', path: '/api/tables', domain: ApiDomain.EDGE, purpose: 'local edge DB inspection' },
  { method: 'GET', path: '/api/opcua/status', domain: ApiDomain.EDGE, purpose: 'OPC UA poller runtime status' },
  { method: 'GET', path: '/api/opcua/catalog', domain: ApiDomain.EDGE, purpose: 'edge OPC UA signal catalog and live values' },
  { method: 'GET', path: '/api/signals/catalog', domain: ApiDomain.SHARED, purpose: 'shared signal catalog; edge reads field facts' },
  { method: 'PUT', path: '/api/signals/:id', domain: ApiDomain.EDGE, purpose: 'edge-owned source_addr/display_name maintenance' },
  { method: 'PUT', path: '/api/opcua/selection', domain: ApiDomain.EDGE, purpose: 'edge OPC UA collection enablement' },
  { method: 'POST', path: '/api/opcua/start', domain: ApiDomain.EDGE, purpose: 'edge OPC UA control' },
  { method: 'POST', path: '/api/opcua/stop', domain: ApiDomain.EDGE, purpose: 'edge OPC UA control' },
  { method: 'GET', path: '/api/ni/status', domain: ApiDomain.EDGE, purpose: 'edge NI collector status' },
  { method: 'POST', path: '/api/ni/start', domain: ApiDomain.EDGE, purpose: 'edge NI collector control' },
  { method: 'POST', path: '/api/ni/stop', domain: ApiDomain.EDGE, purpose: 'edge NI collector control' },
  { method: 'POST', path: '/api/ni/capture', domain: ApiDomain.EDGE, purpose: 'edge raw waveform capture' },
  { method: 'GET', path: '/api/vib/sessions', domain: ApiDomain.EDGE, purpose: 'edge vibration sessions' },
  { method: 'GET', path: '/api/vib/features', domain: ApiDomain.EDGE, purpose: 'edge vibration features' },
  { method: 'GET', path: '/api/vib/events', domain: ApiDomain.EDGE, purpose: 'edge vibration events' },
  { method: 'GET', path: '/api/vib/block', domain: ApiDomain.EDGE, purpose: 'edge raw waveform block read' },
  { method: 'GET', path: '/api/export/vib/block', domain: ApiDomain.EDGE, purpose: 'edge raw block export' },
  { method: 'GET', path: '/api/export/vib/features', domain: ApiDomain.EDGE, purpose: 'edge feature export' },
  { method: 'GET', path: '/api/export/opcua', domain: ApiDomain.EDGE, purpose: 'edge OPC UA export' },
  { method: 'GET', path: '/api/config', domain: ApiDomain.EDGE, purpose: 'edge acquisition config read' },
  { method: 'PUT', path: '/api/config', domain: ApiDomain.EDGE, purpose: 'edge acquisition config write' },
  { method: 'GET', path: '/api/spindle/trend', domain: ApiDomain.EDGE, purpose: 'edge legacy OPC UA spindle trend' },
  { method: 'GET', path: '/api/axes/trend', domain: ApiDomain.EDGE, purpose: 'edge legacy OPC UA axes trend' },
  { method: 'GET', path: '/api/coordinates', domain: ApiDomain.EDGE, purpose: 'edge legacy OPC UA coordinates' },
  { method: 'GET', path: '/api/vibration/range', domain: ApiDomain.EDGE, purpose: 'edge legacy vibration table range' },
  { method: 'GET', path: '/api/vibration', domain: ApiDomain.EDGE, purpose: 'edge legacy vibration table read' },
]);

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

let activeMachineId = EDGE_MACHINE_ID;

function reqMachine(req) {
  const raw = req.query.machine_id || req.body?.machine_id || req.headers['x-machine-id'];
  const mid = normalizeMachineId(raw);
  if (raw) activeMachineId = mid;
  return mid;
}

let opcuaDesiredSignature = null;
let reconciling = false;

function opcuaSignature(cfg) {
  const desired = !!(cfg.control?.opcua_run ?? cfg.opcua?.enabled);
  if (!desired) return 'off';
  const o = cfg.opcua || {};
  const enabledSignalIds = Array.isArray(o.enabledSignalIds)
    ? o.enabledSignalIds.map(Number).filter((x) => Number.isInteger(x)).sort((a, b) => a - b)
    : null;
  return JSON.stringify({
    endpoint: o.endpoint,
    username: o.username,
    password: o.password,
    anonymous: !!o.anonymous,
    pollIntervalMs: Number(o.pollIntervalMs || 1000),
    profile: o.profile,
    enabledSignalIds,
  });
}

function invalidateOpcuaDirectory() {
  opcuaDesiredSignature = null;
}

async function reconcileOpcua(machineId = EDGE_MACHINE_ID) {
  if (reconciling) return;
  reconciling = true;
  try {
    const cfg = await getConfig(machineId);
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
      enabled: s.collect_enabled !== false,
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
  res.json({ status: 'ok', db: process.env.PGDATABASE || 'vibration_db', machineId: reqMachine(req), defaultMachineId: EDGE_MACHINE_ID });
}));

app.get('/api/tables', wrap(async (req, res) => {
  res.json(await repo.listTables());
}));

app.get('/api/opcua/status', wrap(async (req, res) => {
  res.json(opcuaStatus());
}));

app.get('/api/opcua/catalog', wrap(async (req, res) => {
  const mid = reqMachine(req);
  const cfg = await getConfig(mid);
  const st = opcuaStatus();
  const [r2, r3, rnew] = await Promise.all([
    repo.getLatestRow('_OPCUA_2'),
    repo.getLatestRow('_OPCUA_3'),
    repo.getLatestRow('_OPCUA_new'),
  ]);

  let signalRows = [];
  try {
    signalRows = await getSignals(mid);
  } catch (err) {
    console.warn('[signal] catalog unavailable:', err.message);
  }

  const opcuaRows = signalRows.filter((s) => String(s.protocol || '').toLowerCase() === 'opcua');
  const groups = opcuaRows.length
    ? groupSignals(opcuaRows, { r2, r3, rnew })
    : [{ table: 'phm_v2.signal', title: '未建档', latestTime: null, signals: [] }];

  const maps = buildOpcua(cfg.opcua.profile);
  res.json({
    machineId: mid,
    defaultMachineId: EDGE_MACHINE_ID,
    profile: cfg.opcua.profile,
    endpoint: cfg.opcua.endpoint,
    pollIntervalMs: cfg.opcua.pollIntervalMs,
    enabled: !!(cfg.control?.opcua_run ?? cfg.opcua.enabled),
    status: { running: st.running, connected: st.connected, lastError: st.lastError, lastOkAt: st.lastOkAt },
    nodeCount: maps.allNodeIds.length,
    source: opcuaRows.length ? 'phm_v2.signal' : 'unfiled',
    groups,
    legacyMaps: {
      opcua2: maps.OPCUA2_MAP.length,
      opcua3: maps.OPCUA3_MAP.length + DERIVED_OPCUA3.length,
      coords: maps.OPCUA_NEW_MAP.length,
    },
  });
}));

app.get('/api/signals/catalog', wrap(async (req, res) => {
  const mid = reqMachine(req);
  let rows = [];
  try { rows = await getSignals(mid); } catch { rows = []; }
  res.json({ machineId: mid, defaultMachineId: EDGE_MACHINE_ID, source: rows.length ? 'phm_v2.signal' : 'unfiled', signals: rows });
}));

app.put('/api/signals/:id', wrap(async (req, res) => {
  const row = await updateSignal(req.params.id, req.body || {}, reqMachine(req));
  if (!row) return res.status(404).json({ ok: false, error: 'signal not found or no editable fields' });
  invalidateOpcuaDirectory();
  await reconcileOpcua(reqMachine(req));
  res.json({ ok: true, signal_id: row.signal_id, opcua: opcuaStatus() });
}));

app.put('/api/opcua/selection', wrap(async (req, res) => {
  const ids = Array.isArray(req.body?.enabledSignalIds) ? req.body.enabledSignalIds : [];
  const cfg = await saveOpcuaSelection(ids, reqMachine(req));
  invalidateOpcuaDirectory();
  await reconcileOpcua(reqMachine(req));
  res.json({ ok: true, enabledSignalIds: cfg.opcua.enabledSignalIds || [], opcua: opcuaStatus() });
}));

app.post('/api/opcua/start', wrap(async (req, res) => {
  await saveConfig({ opcua: { enabled: true }, control: { opcua_run: true } }, reqMachine(req));
  await reconcileOpcua(reqMachine(req));
  res.json({ ok: true, opcua: opcuaStatus() });
}));
app.post('/api/opcua/stop', wrap(async (req, res) => {
  await saveConfig({ opcua: { enabled: false }, control: { opcua_run: false } }, reqMachine(req));
  await reconcileOpcua(reqMachine(req));
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
  const mid = reqMachine(req);
  res.json({ ...(await getConfig(mid)), machineId: mid, defaultMachineId: EDGE_MACHINE_ID });
}));

app.put('/api/config', wrap(async (req, res) => {
  const mid = reqMachine(req);
  const next = await saveConfig(req.body || {}, mid);
  await reconcileOpcua(mid);
  res.json({ saved: true, machineId: mid, config: next, opcua: opcuaStatus() });
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

app.get(['/edge', '/edge/'], (req, res) => {
  res.sendFile(path.join(WEB_ROOT, 'index.html'));
});
app.get('/edge/config', (req, res) => {
  res.sendFile(path.join(WEB_ROOT, 'config.html'));
});
app.get('/edge/signals', (req, res) => {
  res.sendFile(path.join(WEB_ROOT, 'signals.html'));
});

app.use('/', express.static(WEB_ROOT));

app.listen(PORT, async () => {
  console.log(`dashboard/acquisition backend started: http://localhost:${PORT}`);
  console.log(`db: ${process.env.PGDATABASE || 'vibration_db'} @ ${process.env.PGHOST || 'localhost'}:${process.env.PGPORT || 5432}`);
  console.log(`edge machine: ${EDGE_MACHINE_ID}`);

  try {
    await ensureConfigTable();
    await ensureControlTable();
    await reconcileOpcua();
    setInterval(() => reconcileOpcua(activeMachineId), 1000).unref();
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





