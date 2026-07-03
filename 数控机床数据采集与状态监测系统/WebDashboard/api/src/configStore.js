import { query } from './db.js';
import { connection } from './opcua/config.js';

export const EDGE_MACHINE_ID = process.env.EDGE_MACHINE_ID || 'FIELD_2026_06_18';
export function normalizeMachineId(machineId) {
  return String(machineId || EDGE_MACHINE_ID).trim() || EDGE_MACHINE_ID;
}

const DEFAULTS = {
  edge: {
    mode: 'edge_gateway',
    gatewayId: process.env.EDGE_GATEWAY_ID || EDGE_MACHINE_ID,
    baseUrl: process.env.EDGE_BASE_URL || `http://localhost:${process.env.PORT || 4000}`,
  },
  acquisition: {
    source: 'simulated',
    rate: 25600,
    samplesPerChannel: 1600,
    inputBufferSize: 300000,
    tableBaseName: 'tb_dev',
    featureWindowSamples: 0,
    eventEnabled: false,
    eventRmsThresholdG: 0,
    channels: [
      { physicalChannel: 'cDAQ1Mod4/ai0', sensitivityMvPerG: 98.94 },
      { physicalChannel: 'cDAQ1Mod4/ai1', sensitivityMvPerG: 98.94 },
      { physicalChannel: 'cDAQ1Mod4/ai2', sensitivityMvPerG: 98.94 },
      { physicalChannel: 'cDAQ1Mod4/ai3', sensitivityMvPerG: 98.94 },
    ],
  },
  opcua: {
    enabled: (process.env.OPCUA_ENABLED || 'false') === 'true',
    profile: connection.profile,
    endpoint: connection.endpoint,
    anonymous: connection.anonymous,
    username: connection.username,
    password: connection.password,
    pollIntervalMs: connection.pollIntervalMs,
  },
  nclink: { host: '', port: 8080, sn: '' },
  control: {
    ni_run: false,
    opcua_run: false,
    capture_seq: 0,
    capture_done: 0,
    ni_state: 'idle',
    ni_message: '',
    ni_heartbeat: null,
    ni_rows: 0,
    ni_sps: 0,
    session: null,
  },
};

export async function ensureConfigTable() {
  await query('CREATE SCHEMA IF NOT EXISTS phm_v2');
  await query(`CREATE TABLE IF NOT EXISTS phm_v2.machine (
    machine_id TEXT PRIMARY KEY,
    cnc_system TEXT,
    model TEXT,
    current_epoch INT NOT NULL DEFAULT 1,
    note TEXT
  )`);
  await query(`CREATE TABLE IF NOT EXISTS phm_v2.acq_config (
    machine_id TEXT PRIMARY KEY REFERENCES phm_v2.machine(machine_id),
    data JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT now()
  )`);
  await query(
    'INSERT INTO phm_v2.machine (machine_id, cnc_system, current_epoch, note) VALUES ($1, $2, 1, $3) ' +
    'ON CONFLICT (machine_id) DO NOTHING',
    [EDGE_MACHINE_ID, 'siemens_840d', 'edge gateway default machine']
  );
  const { rows } = await query('SELECT 1 FROM phm_v2.acq_config WHERE machine_id=$1', [EDGE_MACHINE_ID]);
  if (rows.length === 0) {
    await query('INSERT INTO phm_v2.acq_config (machine_id, data) VALUES ($1, $2)', [
      EDGE_MACHINE_ID,
      JSON.stringify(DEFAULTS),
    ]);
  }

  await query(`CREATE TABLE IF NOT EXISTS app_config (
    id INT PRIMARY KEY,
    data JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT now()
  )`);
  const legacy = await query('SELECT 1 FROM app_config WHERE id=1');
  if (legacy.rows.length === 0) {
    await query('INSERT INTO app_config (id, data) VALUES (1, $1)', [JSON.stringify(DEFAULTS)]);
  }
}

function mergeConfig(data = {}) {
  return {
    edge: { ...DEFAULTS.edge, ...(data.edge || {}) },
    acquisition: { ...DEFAULTS.acquisition, ...(data.acquisition || {}) },
    opcua: { ...DEFAULTS.opcua, ...(data.opcua || {}) },
    nclink: { ...DEFAULTS.nclink, ...(data.nclink || {}) },
    control: { ...DEFAULTS.control, ...(data.control || {}) },
  };
}

async function getLegacyConfig() {
  const { rows } = await query('SELECT data FROM app_config WHERE id=1');
  return rows.length ? mergeConfig(rows[0].data) : structuredClone(DEFAULTS);
}

async function ensureMachineConfig(machineId = EDGE_MACHINE_ID) {
  const mid = normalizeMachineId(machineId);
  await query(
    'INSERT INTO phm_v2.machine (machine_id, cnc_system, current_epoch, note) VALUES ($1, $2, 1, $3) ' +
    'ON CONFLICT (machine_id) DO NOTHING',
    [mid, 'unknown', 'edge gateway managed machine']
  );
  const { rows } = await query('SELECT 1 FROM phm_v2.acq_config WHERE machine_id=$1', [mid]);
  if (rows.length === 0) {
    const seed = mergeConfig({ edge: { gatewayId: mid } });
    await query('INSERT INTO phm_v2.acq_config (machine_id, data) VALUES ($1, $2)', [
      mid,
      JSON.stringify(seed),
    ]);
  }
  return mid;
}

export async function getConfig(machineId = EDGE_MACHINE_ID) {
  const mid = normalizeMachineId(machineId);
  try {
    await ensureMachineConfig(mid);
    const { rows } = await query('SELECT data FROM phm_v2.acq_config WHERE machine_id=$1', [mid]);
    if (rows.length) return mergeConfig(rows[0].data);
  } catch (err) {
    console.warn(`[config] phm_v2.acq_config unavailable, using legacy app_config: ${err.message}`);
    return getLegacyConfig();
  }
  return structuredClone(DEFAULTS);
}

export async function saveConfig(patch, machineId = EDGE_MACHINE_ID) {
  const mid = normalizeMachineId(machineId);
  const cur = await getConfig(mid);
  const next = {
    edge: { ...cur.edge, ...(patch.edge || {}) },
    acquisition: { ...cur.acquisition, ...(patch.acquisition || {}) },
    opcua: { ...cur.opcua, ...(patch.opcua || {}) },
    nclink: { ...cur.nclink, ...(patch.nclink || {}) },
    control: { ...cur.control, ...(patch.control || {}) },
  };
  try {
    await query(
      'INSERT INTO phm_v2.acq_config (machine_id, data, updated_at) VALUES ($1, $2, now()) ' +
      'ON CONFLICT (machine_id) DO UPDATE SET data = EXCLUDED.data, updated_at = now()',
      [mid, JSON.stringify(next)]
    );
  } catch (err) {
    console.warn(`[config] save to phm_v2.acq_config failed, writing legacy app_config: ${err.message}`);
    await query(
      'INSERT INTO app_config (id, data, updated_at) VALUES (1, $1, now()) ' +
      'ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data, updated_at = now()',
      [JSON.stringify(next)]
    );
  }
  return next;
}

async function getSignalRows(machineId = EDGE_MACHINE_ID) {
  const mid = normalizeMachineId(machineId);
  const { rows } = await query(
    `SELECT signal_id, code, display_name, unit, protocol, source_addr, phm_system,
            signal_kind, temp_role, regime_role, is_high_freq
       FROM phm_v2.signal
      WHERE machine_id=$1
      ORDER BY is_high_freq DESC, phm_system, code`,
    [mid]
  );
  return rows;
}

export async function getSignals(machineId = EDGE_MACHINE_ID) {
  const mid = normalizeMachineId(machineId);
  const [rows, cfg] = await Promise.all([getSignalRows(mid), getConfig(mid)]);
  const selected = Array.isArray(cfg.opcua?.enabledSignalIds) ? new Set(cfg.opcua.enabledSignalIds.map(Number)) : null;
  return rows.map((r) => ({ ...r, collect_enabled: selected ? selected.has(Number(r.signal_id)) : true }));
}

export async function updateSignal(signalId, patch = {}, machineId = EDGE_MACHINE_ID) {
  const mid = normalizeMachineId(machineId);
  const allowed = {};
  if (Object.prototype.hasOwnProperty.call(patch, 'source_addr')) allowed.source_addr = String(patch.source_addr || '').trim();
  if (Object.prototype.hasOwnProperty.call(patch, 'display_name')) allowed.display_name = String(patch.display_name || '').trim();
  const entries = Object.entries(allowed);
  if (!entries.length) return null;
  const sets = entries.map(([k], i) => `${k}=$${i + 2}`).join(', ');
  const { rows } = await query(
    `UPDATE phm_v2.signal SET ${sets} WHERE machine_id=$1 AND signal_id=$${entries.length + 2} RETURNING signal_id`,
    [mid, ...entries.map(([, v]) => v), Number(signalId)]
  );
  return rows[0] || null;
}

export async function saveOpcuaSelection(enabledSignalIds = [], machineId = EDGE_MACHINE_ID) {
  const ids = enabledSignalIds.map(Number).filter((x) => Number.isInteger(x) && x > 0);
  return saveConfig({ opcua: { enabledSignalIds: ids } }, machineId);
}

export { DEFAULTS, mergeConfig };
