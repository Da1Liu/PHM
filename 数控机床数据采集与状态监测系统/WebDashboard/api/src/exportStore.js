import { query } from './db.js';

// 原始数据导出（供机器学习算法验证）。
// 三类来源 -> CSV：
//   ① vib_raw_blocks  单次抓取/事件的完整 float32 原始波形（采样点×通道）
//   ② vib_features    每窗每通道的 7 项统计量（算法核直接消费层）
//   ③ _OPCUA_2/3/new  低频状态量整段（协变量/工况分层验证）
// 格式：CSV + 元数据。文件顶部以 `#` 注释承载元数据——
//   第一行 `# META: {json}` 机器可解析；其后人类可读。
//   numpy/pandas 用 comment='#' 跳过注释、首个非注释行即列名。
// 不引入新依赖（zip 等）：一次请求导出一个文件，HTTP attachment 下载。

const FEATURE_COLS = ['mean', 'rms', 'peak', 'p2p', 'std', 'kurtosis', 'crest'];
const OPCUA_TABLES = { opcua2: '_OPCUA_2', opcua3: '_OPCUA_3', opcuanew: '_OPCUA_new' };

// —— CSV 基础工具 ——
function csvCell(v) {
  if (v == null) return '';
  if (v instanceof Date) return v.toISOString();
  if (typeof v === 'number') return Number.isFinite(v) ? String(v) : '';
  const s = String(v);
  return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}
function csvRow(cells) { return cells.map(csvCell).join(','); }

// 注释行保持纯 ASCII：numpy.genfromtxt 会逐行读取(含注释)再跳过，若注释含中文则
// 在 Windows 默认 GBK 编码下解码报错。元数据用 ASCII 英文 + JSON(值通常亦 ASCII)，
// 使整个文件在常见数据下 ASCII-safe，任意编码均可读。
function metaHeader(meta) {
  return '# META: ' + JSON.stringify(meta) + '\n'
    + '# Exported by CNC acquisition system for ML validation. Full metadata = the JSON on the line above.\n'
    + `# type: ${meta.type}  n_rows: ${meta.n_rows ?? ''}  exported_at: ${new Date().toISOString()}\n`;
}

function stamp() {
  return new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
}
function safeName(s) {
  return String(s || 'session').replace(/[^A-Za-z0-9_.-]/g, '_').slice(0, 60);
}

// bytea(Buffer) float32 小端 -> 全分辨率 number[]（导出不抽稀，ML 要原始）
function decodeFull(buf, nSamples) {
  const total = Math.min(nSamples, Math.floor(buf.length / 4));
  const out = new Array(total);
  for (let i = 0; i < total; i++) out[i] = buf.readFloatLE(i * 4);
  return out;
}

// ① 单次抓取/事件的原始波形块 -> 宽表 CSV：sample_idx, t_s, ch<c>_g ...
export async function buildRawBlockCsv(eventId) {
  const id = Number(eventId);
  const { rows } = await query(
    `SELECT b.channel, b.time_start, b.rate, b.n_samples, b.data,
            e."trigger", e."time" AS event_time, e.session
       FROM vib_raw_blocks b JOIN vib_events e ON e.id = b.event_id
      WHERE b.event_id = $1 ORDER BY b.channel ASC`, [id]);
  if (!rows.length) { const err = new Error(`事件 ${id} 无原始块`); err.status = 404; throw err; }

  const channels = rows.map((r) => ({
    channel: r.channel,
    rate: r.rate,
    data: decodeFull(r.data, r.n_samples),
  }));
  const rate = Number(rows[0].rate) || Number(channels[0].rate) || 0;
  const maxLen = channels.reduce((m, c) => Math.max(m, c.data.length), 0);

  const meta = {
    type: 'vib_raw_block',
    event_id: id,
    session: rows[0].session,
    trigger: rows[0].trigger,
    event_time: rows[0].event_time,
    rate_hz: rate,
    unit: 'g',
    n_rows: maxLen,
    channels: channels.map((c) => ({ channel: c.channel, n_samples: c.data.length, rate_hz: Number(c.rate) || rate })),
    columns: ['sample_idx', 't_s', ...channels.map((c) => `ch${c.channel}_g`)],
  };

  const parts = [metaHeader(meta), meta.columns.join(',') + '\n'];
  const r = rate || 1;
  for (let i = 0; i < maxLen; i++) {
    const cells = [i, i / r];
    for (const c of channels) cells.push(i < c.data.length ? c.data[i] : null);
    parts.push(csvRow(cells) + '\n');
  }
  return { filename: `vib_block_event${id}_${safeName(rows[0].session)}.csv`, csv: parts.join('') };
}

// ② 特征流 vib_features -> 长表 CSV：time, session, channel, <7 metrics>
export async function buildFeaturesCsv({ from, to, channels }) {
  const params = [];
  const conds = [];
  if (channels && channels.length) { params.push(channels.map(Number)); conds.push(`channel = ANY($${params.length})`); }
  if (from) { params.push(from); conds.push(`"time" >= $${params.length}`); }
  if (to) { params.push(to); conds.push(`"time" <= $${params.length}`); }
  const where = conds.length ? `WHERE ${conds.join(' AND ')}` : '';
  const { rows } = await query(
    `SELECT "time", session, channel, ${FEATURE_COLS.join(', ')}
       FROM vib_features ${where} ORDER BY "time" ASC, channel ASC`, params);

  const columns = ['time', 'session', 'channel', ...FEATURE_COLS];
  const meta = {
    type: 'vib_features',
    from: from || null, to: to || null,
    channels: channels && channels.length ? channels : 'all',
    n_rows: rows.length, columns,
  };
  const parts = [metaHeader(meta), columns.join(',') + '\n'];
  for (const r of rows) {
    parts.push(csvRow([r.time, r.session, r.channel, ...FEATURE_COLS.map((c) => r[c])]) + '\n');
  }
  return { filename: `vib_features_${stamp()}.csv`, csv: parts.join('') };
}

// ③ OPC UA 状态量整段 -> 宽表 CSV（表全列）。maxPoints>0 时按 id 等距抽稀。
export async function buildOpcuaCsv({ key, from, to, maxPoints = 0 }) {
  const table = OPCUA_TABLES[key];
  if (!table) { const e = new Error(`未知 OPC UA 表: ${key}`); e.status = 400; throw e; }

  const params = [];
  const conds = [];
  if (from) { params.push(from); conds.push(`"time" >= $${params.length}`); }
  if (to) { params.push(to); conds.push(`"time" <= $${params.length}`); }
  const where = conds.length ? `WHERE ${conds.join(' AND ')}` : '';

  const mp = Number(maxPoints) || 0;
  const sql = mp > 0
    ? `WITH src AS (
         SELECT *, row_number() OVER (ORDER BY id) AS rn, count(*) OVER () AS cnt
           FROM "${table}" ${where}
       )
       SELECT * FROM src WHERE rn % GREATEST(1, (cnt / ${mp})::int) = 0 ORDER BY rn`
    : `SELECT * FROM "${table}" ${where} ORDER BY id`;

  const result = await query(sql, params);
  const cols = result.fields.map((f) => f.name).filter((c) => c !== 'rn' && c !== 'cnt');
  const meta = {
    type: 'opcua', table, key,
    from: from || null, to: to || null,
    downsample_max: mp || null,
    n_rows: result.rows.length, columns: cols,
  };
  const parts = [metaHeader(meta), cols.join(',') + '\n'];
  for (const r of result.rows) parts.push(csvRow(cols.map((c) => r[c])) + '\n');
  return { filename: `opcua_${key}_${stamp()}.csv`, csv: parts.join('') };
}
