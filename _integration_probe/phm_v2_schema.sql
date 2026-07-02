-- phm_v2 统一数据契约 (隔离 schema, 可 DROP SCHEMA phm_v2 CASCADE 回滚)
-- 不建 health_result (本阶段缓); 不动 public 现有表。
CREATE SCHEMA IF NOT EXISTS phm_v2;
SET search_path TO phm_v2;

-- 机床维表
CREATE TABLE IF NOT EXISTS machine (
  machine_id    TEXT PRIMARY KEY,
  cnc_system    TEXT,
  model         TEXT,
  current_epoch INT NOT NULL DEFAULT 1,
  note          TEXT
);

-- 信号定义维表 (= channel_map 的数据库版)
CREATE TABLE IF NOT EXISTS signal (
  signal_id    BIGSERIAL PRIMARY KEY,
  machine_id   TEXT NOT NULL REFERENCES machine(machine_id),
  code         TEXT NOT NULL,
  display_name TEXT,
  unit         TEXT,
  protocol     TEXT NOT NULL,            -- nclink | opcua | ni_daq | ...
  source_addr  TEXT,                     -- NC-Link path@index / OPC UA NodeId / NI 通道
  phm_system   TEXT,                     -- feed | spindle | hydraulic
  signal_kind  TEXT NOT NULL,            -- vibration|current|speed|position|temperature|pressure|bool
  temp_role    TEXT,                     -- confound | coupled | NULL
  regime_role  BOOLEAN DEFAULT FALSE,
  is_high_freq BOOLEAN DEFAULT FALSE,
  UNIQUE (machine_id, code)
);

-- 标量遥测长表 (OPC UA/NC-Link 标量 + 振动窗特征统一), 按月分区
CREATE TABLE IF NOT EXISTS telemetry (
  machine_id TEXT NOT NULL,
  signal_id  BIGINT NOT NULL REFERENCES signal(signal_id),
  ts         TIMESTAMPTZ NOT NULL,
  value      DOUBLE PRECISION,
  feature    TEXT,                       -- NULL=原生标量; rms/std/kurtosis/crest/p2p/...=振动窗特征
  epoch      INT NOT NULL DEFAULT 1,
  regime     TEXT
) PARTITION BY RANGE (ts);
CREATE INDEX IF NOT EXISTS ix_telemetry_sig_ts     ON telemetry (signal_id, ts);
CREATE INDEX IF NOT EXISTS ix_telemetry_machine_ts ON telemetry (machine_id, ts);

-- 干跑用分区 (实测数据在 2026-06)
CREATE TABLE IF NOT EXISTS telemetry_2026_06 PARTITION OF telemetry
  FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');

-- 原始波形块 (沿用现结构, 补 machine_id/epoch, channel->signal_id)
CREATE TABLE IF NOT EXISTS vib_raw_blocks (
  id         BIGSERIAL PRIMARY KEY,
  machine_id TEXT NOT NULL,
  signal_id  BIGINT REFERENCES signal(signal_id),
  epoch      INT NOT NULL DEFAULT 1,
  event_id   BIGINT,
  time_start TIMESTAMPTZ NOT NULL,
  rate       INT NOT NULL,
  n_samples  INT NOT NULL,
  data       BYTEA NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_v2_raw_sig_time ON vib_raw_blocks (signal_id, time_start);

-- 种子: 实测机床 + 4 振动测点 (假定映射, 可改)
INSERT INTO machine (machine_id, cnc_system, model, current_epoch, note)
VALUES ('FIELD_2026_06_18', 'unknown', 'heavy_mill', 1, '现场实测振动来源, 单段标定用')
ON CONFLICT (machine_id) DO NOTHING;

INSERT INTO signal (machine_id, code, display_name, unit, protocol, source_addr,
                    phm_system, signal_kind, temp_role, regime_role, is_high_freq)
VALUES
 ('FIELD_2026_06_18','vib_gearbox_1','主传动变速箱箱体振动1','g','ni_daq','cDAQ1Mod4/ai0','spindle','vibration',NULL,FALSE,TRUE),
 ('FIELD_2026_06_18','vib_gearbox_2','主传动变速箱箱体振动2','g','ni_daq','cDAQ1Mod4/ai1','spindle','vibration',NULL,FALSE,TRUE),
 ('FIELD_2026_06_18','vib_gearbox_3','主传动变速箱箱体振动3','g','ni_daq','cDAQ1Mod4/ai2','spindle','vibration',NULL,FALSE,TRUE),
 ('FIELD_2026_06_18','vib_spindle_front_bearing','主轴前轴承套振动','g','ni_daq','cDAQ1Mod4/ai3','spindle','vibration',NULL,FALSE,TRUE)
ON CONFLICT (machine_id, code) DO NOTHING;
