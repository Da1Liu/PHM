import {
  OPCUAClient, AttributeIds, MessageSecurityMode, SecurityPolicy, UserTokenType,
} from 'node-opcua';
import { query } from '../db.js';
import { ensureOpcuaTables } from './schema.js';
import { connection, buildOpcua, deriveOpcua3 } from './config.js';
import { coerce } from './transform.js';

// 后端 OPC UA 轮询：替代桌面端 Form2 的 OPCUA2/3/new_Tick（各 1000ms）。
// 一次批量读全部去重节点，再按 列↔节点↔转换 映射拆分入三张表。
// 运行时配置（地址/账号/profile）来自 DB app_config（见 configStore.js），
// 故 startPoller(cfg) 接收配置；profile 决定节点地址集（kepserver/machine）。
// 跨通道关联：原 reid=振动 id 在解耦架构下不可用 → reid 置 NULL，靠时间戳对齐。

let client = null;
let session = null;
let timer = null;
let running = false;
let lastError = null;
let lastOkAt = null;
let activeCfg = null;

export function getStatus() {
  return {
    running,
    connected: !!session,
    lastError,
    lastOkAt,
    endpoint: activeCfg?.endpoint ?? connection.endpoint,
    profile: activeCfg?.profile ?? connection.profile,
  };
}

export async function startPoller(cfg = {}) {
  if (running) return;
  const c = {
    endpoint: cfg.endpoint ?? connection.endpoint,
    username: cfg.username ?? connection.username,
    password: cfg.password ?? connection.password,
    anonymous: cfg.anonymous ?? connection.anonymous,
    pollIntervalMs: cfg.pollIntervalMs ?? connection.pollIntervalMs,
    profile: cfg.profile ?? connection.profile,
  };
  activeCfg = c;

  const maps = buildOpcua(c.profile);
  const nodeIds = maps.allNodeIds;
  const nodeIndex = new Map(nodeIds.map((id, i) => [id, i]));

  await ensureOpcuaTables();

  client = OPCUAClient.create({
    endpointMustExist: false,
    securityMode: MessageSecurityMode.None,
    securityPolicy: SecurityPolicy.None,
    connectionStrategy: { maxRetry: 3, initialDelay: 1000, maxDelay: 5000 },
  });
  client.on('backoff', (retry, delay) =>
    console.warn(`[opcua] 重连中 retry=${retry} delay=${delay}ms`));

  try {
    await client.connect(c.endpoint);
    const userIdentity = c.anonymous
      ? { type: UserTokenType.Anonymous }
      : { type: UserTokenType.UserName, userName: c.username, password: c.password };
    session = await client.createSession(userIdentity);
    running = true;
    console.log(`[opcua] 已连接 ${c.endpoint}（profile=${c.profile}），轮询 ${c.pollIntervalMs}ms`);
  } catch (err) {
    lastError = err.message;
    console.error(`[opcua] 连接失败: ${err.message}`);
    await stopPoller();
    return;
  }

  const tick = async () => {
    try {
      const nodesToRead = nodeIds.map((nodeId) => ({ nodeId, attributeId: AttributeIds.Value }));
      const results = await session.read(nodesToRead);
      // 与桌面端一致：首节点状态判定整批有效性（node-opcua 用 statusCode.isGood）
      if (!results[0] || !results[0].statusCode.isGood) {
        lastError = 'first node status not good';
        return;
      }
      const raw = (m) => results[nodeIndex.get(m.node)]?.value?.value;

      const now = new Date();
      await insertRow('_OPCUA_2', maps.OPCUA2_MAP, raw, { reid: null });
      const o3 = mapValues(maps.OPCUA3_MAP, raw);
      Object.assign(o3, deriveOpcua3(o3), { time: now });
      await insertMapped('_OPCUA_3', o3);
      await insertRow('_OPCUA_new', maps.OPCUA_NEW_MAP, raw, {}, false);

      lastOkAt = new Date().toISOString();
      lastError = null;
    } catch (err) {
      lastError = err.message;
      console.error(`[opcua] 轮询出错: ${err.message}`);
    }
  };

  timer = setInterval(tick, c.pollIntervalMs);
  tick();
}

// 用新配置重启（PUT /api/config 时调用）
export async function restartPoller(cfg) {
  await stopPoller();
  if (cfg && cfg.enabled !== false) await startPoller(cfg);
}

function mapValues(map, raw) {
  const out = {};
  for (const m of map) out[m.col] = coerce(raw(m), m.type);
  return out;
}

// withTime: _OPCUA_2/_3 用 TIMESTAMP WITHOUT TIME ZONE，写 now；_OPCUA_new 有默认 CURRENT_TIMESTAMP
async function insertRow(table, map, raw, extra = {}, withTime = true) {
  const values = mapValues(map, raw);
  Object.assign(values, extra);
  if (withTime) values.time = new Date();
  await insertMapped(table, values);
}

async function insertMapped(table, values) {
  const cols = Object.keys(values);
  if (!cols.length) return;
  const params = cols.map((_, i) => `$${i + 1}`);
  const sql = `INSERT INTO "${table}" (${cols.map((c) => `"${c}"`).join(', ')}) VALUES (${params.join(', ')})`;
  await query(sql, cols.map((c) => values[c]));
}

export async function stopPoller() {
  running = false;
  if (timer) { clearInterval(timer); timer = null; }
  try { if (session) await session.close(); } catch { /* ignore */ }
  try { if (client) await client.disconnect(); } catch { /* ignore */ }
  session = null;
  client = null;
}
