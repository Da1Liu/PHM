-- phm_v2.health_result: PHM 评分回写表 (闭环最后一环).
-- 中心只读看板直接读本表渲染 (显示字段 mode/light/message/target_n 由评分侧算好写入,
-- 看板不再依赖 config). 可 DROP TABLE phm_v2.health_result 回滚.
-- 对应 dashboard.py /api/sync 的 UPSERT TODO: UNIQUE 键幂等去重.
SET search_path TO phm_v2;

CREATE TABLE IF NOT EXISTS health_result (
  id          BIGSERIAL PRIMARY KEY,
  machine_id  TEXT NOT NULL,
  phm_system  TEXT NOT NULL,            -- spindle | feed | hydraulic
  epoch       INT  NOT NULL DEFAULT 1,
  regime      TEXT NOT NULL DEFAULT 'default',  -- baseline_key 序列化 (单基线='default')
  ts          TIMESTAMPTZ NOT NULL,     -- 样本(采集窗)时间戳

  -- 评分核心
  health      DOUBLE PRECISION,
  score       DOUBLE PRECISION,         -- max(T2/UCL_T2, SPE/UCL_SPE)
  t2          DOUBLE PRECISION,         -- Phase 2 [已填, 2026-06-24] 成熟期 Hotelling T2
  spe         DOUBLE PRECISION,         -- Phase 2 [已填] 残差平方和 SPE
  ucl_t2      DOUBLE PRECISION,
  ucl_spe     DOUBLE PRECISION,

  -- 生命周期
  stage       INT,                      -- 1 工程先验 / 2 分位 / 3 成熟 PCA+T2+SPE
  n           INT,                      -- 该 regime 当前基线样本数
  n_days      INT,
  target_n    INT,                      -- 进成熟期门槛 (mature_min_n), 建立期 x/N 的 N
  admitted    BOOLEAN,                  -- 是否并入基线池
  steady      BOOLEAN,                  -- 是否判为稳态

  -- 看板直接显示 (评分侧算好, 中心只读)
  mode        TEXT,                     -- building | scoring | status_only
  light       TEXT,                     -- building | green | yellow | red
  message     TEXT,
  contributions JSONB,                  -- Phase 2 [已填] 逐特征贡献 [{name,t2,spe}] (diagnose 页)

  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (machine_id, phm_system, epoch, regime, ts)
);

CREATE INDEX IF NOT EXISTS ix_health_machine_sys_ts
  ON health_result (machine_id, phm_system, epoch, ts);
