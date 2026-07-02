import { query } from './db.js';

// 固定的实时累积表（桌面程序在 Form2 构造时建好、持续写入），看板直接读这些。
export const FIXED_TABLES = {
  opcua2: '_OPCUA_2', // 主轴电流/温度/转速
  opcua3: '_OPCUA_3', // 各轴电流/温度/速度 + 油泵布尔量
  coords: '_OPCUA_new', // 机械/绝对坐标
};

// 进给系统各轴（对应 _OPCUA_3 的列前缀，与桌面端 Form4 顺序一致）
export const AXES = ['x1', 'x2', 'y1', 'y2', 'z', 'w', 'v', 'b1', 'b2'];

// 表名白名单校验：只允许字母数字下划线，且必须是库中真实存在的表，杜绝 SQL 注入。
// 振动结果表名是动态的（tb_YYYY_..._main），不能写死，故走"存在性校验"。
const SAFE_NAME = /^[A-Za-z0-9_]+$/;

export async function listTables() {
  const { rows } = await query(
    `SELECT table_name
       FROM information_schema.tables
      WHERE table_schema = 'public'
        AND table_type = 'BASE TABLE'
      ORDER BY table_name`
  );
  const all = rows.map((r) => r.table_name);
  return {
    vibration: all.filter((t) => /_main$/.test(t) && t !== '_OPCUA_2'),
    bool: all.filter((t) => /_bool$/.test(t)),
    other: all.filter((t) => /_other$/.test(t)),
    fixed: all.filter((t) => Object.values(FIXED_TABLES).includes(t)),
    all,
  };
}

async function tableExists(table) {
  if (!SAFE_NAME.test(table)) return false;
  const { rows } = await query(
    `SELECT 1 FROM information_schema.tables
      WHERE table_schema='public' AND table_name=$1 LIMIT 1`,
    [table]
  );
  return rows.length > 0;
}

// 列出某表实际拥有的列（用于动态选列，避免对不存在的列报错）
async function tableColumns(table) {
  const { rows } = await query(
    `SELECT column_name FROM information_schema.columns
      WHERE table_schema='public' AND table_name=$1`,
    [table]
  );
  return new Set(rows.map((r) => r.column_name));
}

// 数据库侧降采样：按 id 顺序均匀抽稀到 ~maxPoints 点，减少传输量。
// 对应桌面端 Form2.DownsampleData 的等距抽样，但放到 SQL 里做。
function buildDownsample(selectCols, table, whereSql, params, maxPoints) {
  return `
    WITH src AS (
      SELECT ${selectCols},
             row_number() OVER (ORDER BY id) AS rn,
             count(*) OVER () AS cnt
        FROM "${table}"
        ${whereSql}
    )
    SELECT ${selectCols}
      FROM src
     WHERE rn % GREATEST(1, (cnt / ${Number(maxPoints)})::int) = 0
     ORDER BY rn`;
}

// ---- 主轴趋势 (_OPCUA_2) ----
export async function getSpindleTrend({ from, to, maxPoints }) {
  const table = FIXED_TABLES.opcua2;
  if (!(await tableExists(table))) return { table, columns: [], rows: [] };

  const cols = [
    'id', 'time', 'run_rate', 'motor_speed', 'spindle_current',
    'spindle_motor_temperature', 'spindle_front_bearing_temperature',
    'spindle_rear_bearing_temperature', 'spindle_tail_support_temperature',
  ];
  const { whereSql, params } = timeWhere(from, to);
  const sql = buildDownsample(cols.join(', '), table, whereSql, params, maxPoints);
  const { rows } = await query(sql, params);
  return { table, columns: cols, rows };
}

// ---- 进给各轴趋势 (_OPCUA_3) ----
// metric: current | temperature | speed ; axes: AXES 子集
export async function getAxesTrend({ axes, metric, from, to, maxPoints }) {
  const table = FIXED_TABLES.opcua3;
  if (!(await tableExists(table))) return { table, metric, columns: [], rows: [] };

  const validMetric = ['current', 'temperature', 'speed'].includes(metric) ? metric : 'current';
  const wanted = (axes && axes.length ? axes : AXES).filter((a) => AXES.includes(a));
  const existing = await tableColumns(table);
  const axisCols = wanted
    .map((a) => `${a}_axis_${validMetric}`)
    .filter((c) => existing.has(c));

  const cols = ['id', 'time', ...axisCols];
  const { whereSql, params } = timeWhere(from, to);
  const sql = buildDownsample(cols.join(', '), table, whereSql, params, maxPoints);
  const { rows } = await query(sql, params);
  return { table, metric: validMetric, axes: wanted, columns: cols, rows };
}

// ---- 坐标 (_OPCUA_new) ----
export async function getCoordinates({ from, to, maxPoints }) {
  const table = FIXED_TABLES.coords;
  if (!(await tableExists(table))) return { table, columns: [], rows: [] };

  const cols = [
    'id', 'time',
    'x_mc', 'y_mc', 'z_mc', 'w_mc', 'sp_mc', 'v_mc', 'b_mc', 'u_mc',
    'x_ac', 'y_ac', 'z_ac', 'w_ac', 'sp_ac', 'v_ac', 'b_ac', 'u_ac',
  ];
  const { whereSql, params } = timeWhere(from, to);
  const sql = buildDownsample(cols.join(', '), table, whereSql, params, maxPoints);
  const { rows } = await query(sql, params);
  return { table, columns: cols, rows };
}

// ---- 振动波形（动态表名）----
// channels: 1..N，对应列 channel1..channelN
export async function getVibration({ table, channels, start, end, maxPoints }) {
  if (!(await tableExists(table))) {
    const err = new Error(`表不存在或非法: ${table}`);
    err.status = 404;
    throw err;
  }
  const existing = await tableColumns(table);
  const chCols = (channels && channels.length ? channels : [1, 2, 3, 4])
    .map((n) => `channel${Number(n)}`)
    .filter((c) => existing.has(c));
  if (chCols.length === 0) {
    return { table, columns: [], rows: [] };
  }

  const params = [];
  const conds = [];
  if (start != null) { params.push(Number(start)); conds.push(`id >= $${params.length}`); }
  if (end != null) { params.push(Number(end)); conds.push(`id <= $${params.length}`); }
  const whereSql = conds.length ? `WHERE ${conds.join(' AND ')}` : '';

  const cols = ['id', ...chCols];
  const sql = buildDownsample(cols.join(', '), table, whereSql, params, maxPoints);
  const { rows } = await query(sql, params);
  return { table, columns: cols, rows };
}

// 振动表的 id 游标（首尾），用于前端默认拉取尾部窗口
export async function getIdRange(table) {
  if (!(await tableExists(table))) {
    const err = new Error(`表不存在或非法: ${table}`);
    err.status = 404;
    throw err;
  }
  const { rows } = await query(
    `SELECT COALESCE(MIN(id),0) AS first, COALESCE(MAX(id),0) AS last FROM "${table}"`
  );
  return rows[0];
}

// 某表最新一行（按 id 降序）——供采集信号清单显示"当前实测值 + 最新采样时间"。
// 表不存在（如从未采过 OPC UA）返回 null，前端据此显示"暂无数据"。
export async function getLatestRow(table) {
  if (!(await tableExists(table))) return null;
  const { rows } = await query(`SELECT * FROM "${table}" ORDER BY id DESC LIMIT 1`);
  return rows[0] || null;
}

function timeWhere(from, to) {
  const params = [];
  const conds = [];
  if (from) { params.push(from); conds.push(`time >= $${params.length}`); }
  if (to) { params.push(to); conds.push(`time <= $${params.length}`); }
  const whereSql = conds.length ? `WHERE ${conds.join(' AND ')}` : '';
  return { whereSql, params };
}

export async function ping() {
  await query('SELECT 1');
  return true;
}
