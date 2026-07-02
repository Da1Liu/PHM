-- phm_v2.bridge_state: 采集落库(public) -> phm_v2.telemetry 桥的增量 watermark。
-- 每 (machine_id, source) 记最后已搬运的 ts; 桥只导 time > last_ts, 幂等。
-- pg_bridge.py 运行时亦会 CREATE IF NOT EXISTS 自建, 本文件供契约存档/手工初始化。
CREATE TABLE IF NOT EXISTS phm_v2.bridge_state (
  machine_id TEXT NOT NULL,
  source     TEXT NOT NULL,            -- 'vib_features' (Phase 1); 后续可加 'opcua_2' 等
  last_ts    TIMESTAMPTZ,
  updated_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (machine_id, source)
);
