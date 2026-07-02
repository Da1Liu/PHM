import { query } from './db.js';

// 振动落盘策略的读侧：特征趋势（vib_features）+ 原始波形块（vib_raw_blocks/vib_events）。
// 取代旧的 _main 大表读取：常态看特征趋势，需要看波形时取某次抓取/事件的原始块解码。

const FEATURE_COLS = ['mean', 'rms', 'peak', 'p2p', 'std', 'kurtosis', 'crest'];

// 特征趋势：返回 [{time, channel, <metrics...>}]，前端按 channel 分组成多条曲线。
export async function getFeatures({ channels, from, to, maxPoints = 1000 }) {
  const params = [];
  const conds = [];
  if (channels && channels.length) {
    params.push(channels.map(Number));
    conds.push(`channel = ANY($${params.length})`);
  }
  if (from) { params.push(from); conds.push(`"time" >= $${params.length}`); }
  if (to) { params.push(to); conds.push(`"time" <= $${params.length}`); }
  const where = conds.length ? `WHERE ${conds.join(' AND ')}` : '';
  const step = Math.max(1, Math.ceil(maxPoints)); // 用作每通道返回上限
  // 每通道按时间取最近 step 条（特征本就低频，足够）
  const sql = `
    SELECT "time", channel, ${FEATURE_COLS.join(', ')}
      FROM (
        SELECT *, row_number() OVER (PARTITION BY channel ORDER BY "time" DESC) AS rn
          FROM vib_features ${where}
      ) t
     WHERE rn <= $${params.length + 1}
     ORDER BY "time" ASC, channel ASC`;
  params.push(step);
  const { rows } = await query(sql, params);
  return { metrics: FEATURE_COLS, rows };
}

// 最近的抓取/事件列表（供前端选择查看哪一段原始波形）
export async function listEvents({ limit = 50 } = {}) {
  const { rows } = await query(
    `SELECT e.id, e."time", e.session, e."trigger", e.channel, e.metric_value, e.rate,
            count(b.id) AS n_blocks
       FROM vib_events e LEFT JOIN vib_raw_blocks b ON b.event_id = e.id
      GROUP BY e.id
      ORDER BY e."time" DESC
      LIMIT $1`, [Math.min(Number(limit) || 50, 500)]);
  return rows;
}

// 解码某次事件的原始块（各通道 float32 → 降采样后的数值数组）
export async function getEventBlocks({ eventId, maxPoints = 2000 }) {
  const { rows } = await query(
    `SELECT b.channel, b.time_start, b.rate, b.n_samples, b.data,
            e."trigger", e."time" AS event_time, e.session
       FROM vib_raw_blocks b JOIN vib_events e ON e.id = b.event_id
      WHERE b.event_id = $1 ORDER BY b.channel ASC`, [Number(eventId)]);
  if (!rows.length) return { eventId: Number(eventId), channels: [] };
  const channels = rows.map((r) => ({
    channel: r.channel,
    rate: r.rate,
    nSamples: r.n_samples,
    data: decodeBlock(r.data, r.n_samples, maxPoints),
  }));
  return {
    eventId: Number(eventId),
    trigger: rows[0].trigger,
    session: rows[0].session,
    eventTime: rows[0].event_time,
    rate: rows[0].rate,
    channels,
  };
}

// bytea(Buffer) float32 小端 → JS number[]，按需降采样（每 step 取一点）
function decodeBlock(buf, nSamples, maxPoints) {
  const total = Math.min(nSamples, Math.floor(buf.length / 4));
  const step = Math.max(1, Math.ceil(total / maxPoints));
  const out = [];
  for (let i = 0; i < total; i += step) out.push(buf.readFloatLE(i * 4));
  return out;
}

// 列出有数据的采集会话（按特征表）
export async function listSessions({ limit = 30 } = {}) {
  const { rows } = await query(
    `SELECT session, min("time") AS first, max("time") AS last, count(*) AS n
       FROM vib_features GROUP BY session ORDER BY max("time") DESC LIMIT $1`,
    [Math.min(Number(limit) || 30, 200)]);
  return rows;
}
