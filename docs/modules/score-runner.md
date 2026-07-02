# 评分回写闭环 (score-runner)

> 闭环最后一环: `phm_pipeline/score_runner.py` 把 telemetry → `HealthEngine` 评分 → UPSERT `phm_v2.health_result`。
> 看板显示字段评分侧算好, 中心看板纯读 (不依赖 config)。更新: 2026-06-24。

## 管路
```
[采集器→public.vib_features] → pg_bridge → telemetry        (实时数据的上游, 见 ACQUISITION_CONTRACT §4b)
PostgresSource(telemetry) → CollectionRecord → HealthEngine.observe → HealthResult
→ display_fields(mode/light/message/target_n) → execute_batch UPSERT → health_result
```
> 实时运行时 telemetry 由**采集落库桥** `phm_pipeline.acquisition.pg_bridge` 从现场采集器的 `public.vib_features` 增量搬入 (取代 CSV 回放)。评分前先跑桥。

## CLI (在 `PHM_claude/` 下)
```bash
python -m phm_pipeline.score_runner --machine FIELD_2026_06_18 --system spindle
python -m phm_pipeline.score_runner --machine FIELD_2026_06_18 --system spindle --dry   # 只评分打印, 不写库
python -m phm_pipeline.score_runner --all                # C3: 所有机床×各自系统批量
python -m phm_pipeline.score_runner --all --machine X     # 限定单台所有系统
# 可选 --epoch N (覆盖各机床 current_epoch; 跨 reset 不可比, 慎用)
# --day-mode calendar(默认)|replay  见下「day 模式」
# 复现 FIELD 主轴 stage3 演示需带 --day-mode replay (calendar 下同日 burst 停建立期):
python -m phm_pipeline.score_runner --machine FIELD_2026_06_18 --system spindle --day-mode replay
```
DB 连接参数全部走环境变量 (`PHM_PGHOST/PORT/USER/PGDATABASE`, 默认 `localhost:5432/postgres/vibration_db`);
**`PHM_PGPASSWORD` 必填, 无明文默认** (缺失即清晰报错), 集中于 `phm_pipeline/db_config.py::default_db()`。

## day 模式 (`--day-mode`, 2026-06-30 修复 P4)
`HealthEngine` 的成熟门槛含 `n_days ≥ stage3_min_days`(跨14天); `n_days = len(set(days))`。
喂入的 `day` 由 day-mode 决定:
- **`calendar`(默认, 诚实/生产)**: `day = _calendar_day(rec)` = 记录时间戳的 UTC 日历日序数。真实事件
  节奏 (交班/热机各一条) 下 `n_days` 计真实跨日, 成熟门槛**实际生效**。
- **`replay`(复现 burst 演示)**: `day = 窗序号`。把一段连续标定 burst (FIELD 159 窗/2.5min,
  **同一日历日**) 当逐日事件回放, 否则 calendar 下其 `n_days=1` 永不进成熟期。
> 旧版逐记录 `day+=1` 等价于 replay 且无开关 → `stage3_min_days` 被架空 (14 窗即"跨14天")。现默认 calendar 恢复诚实。

## 关键函数
- `serialize_regime(key)` — baseline_key 元组→文本; 单基线/全 None → `'default'`。
- `display_fields(hr, cfg)` → `(mode, light, message, target_n, n_now)`:
  - `n_now = hr.n + (1 if hr.admitted else 0)` (hr.n 是并入前计数, 修正为当前基线样本数)。
  - `stage≥3` → mode=`scoring`, light = green(>0.6)/yellow(>0.3)/red; 否则 mode=`building`, message=`基线建立中 n_now/target_n`。
- `run_machine_system(..., day_mode="calendar")` — 迭代 records, `if rec.condition.get("system") != system: continue` 收口 (PostgresSource 不按系统过滤), `day` 取 calendar(日历日)/replay(窗序), 幂等 UPSERT (`ON CONFLICT ... DO UPDATE`)。
- `discover_targets(conn, machines=None)` → `[(machine_id, current_epoch, system)]`: 各机床 signal 维表 `phm_system` ∩ `CONFIGS` (仅有评分配置的系统; bool-only 如本台液压→评分 0 记录 no-op)。
- `run_all(conn, machines, epoch_override, dry)` — C3 批量: 遍历 discover_targets, epoch 默认各机床 `current_epoch`, 单 (机床,系统) 异常隔离 (记 `error` 不中断整批)。

## 验收 (FIELD_2026_06_18 主轴, 159 窗; `--day-mode replay`)
走完 建立期(stage1:30 / stage2:30) → 成熟期(stage3:99, 真实 PCA+T²+SPE), 末窗 health=0.31/黄灯; `/api/overview`+trend `source=real`; regression_anchor/smoke PASS。
> 2026-06-30 复核: `replay` 仍得 `stages={1:30,2:30,3:99}`(逐位复现); `calendar` 默认得 `{1:30,2:129,3:0}`(同日 burst 不成熟, 门槛恢复诚实后的**正确**表现); 合成跨18天数据 calendar 下进 stage3 (路径正确)。

## 数据节奏注 (重要, 非 bug)
- 这批是一段 **2.5min 连续标定数据** (同一日历日), `--day-mode replay` 按窗序当"事件样本"回放驱动生命周期。证明"telemetry→评分→health_result→看板"管路通且数值真实; 分期的**运营意义需真实事件节奏数据 (阶段 E)**, 届时用默认 `calendar`。
- **vibration-only 无 steady 通道 → 稳态门控未启用 → 高振瞬态窝进基线池**, 健康偏低偏噪是忠实反映 (印证"真做基线只取稳态窗"), 非 bug。

## Phase 2 (T²/SPE 贡献) [✓done 2026-06-24]
- `BaselineModel.explain(x)` 输出 `{t2,spe,ucl_t2,ucl_spe,score,contributions:[{name,t2,spe}]}`; 贡献精确可加 (Σspe_contrib=SPE / Σt2_contrib=T², T² 单项可负=交叉项, 显示按 0 截断)。
- 经 `LifecycleResult`→`HealthResult` 透传 (stage<3/无模型为 None); `_UPSERT` 补写 `t2/spe/ucl_t2/ucl_spe/contributions(Json 包 JSONB)`。
- 看板 `_real_diagnose` 真实优先读这五列; 诊断页每通道 T²/SPE 双条 (SPE 高亮)。

## Phase 2 剩余待办
- 低频窗聚合分支启用 (等 B2 OPC UA telemetry)。
- 波形读 `vib_raw_blocks` (现 mock)。
- ~~多机床×多系统 score_runner 调度 (C3)~~ [✓done, 见 D6/上文 `--all`]。
- **增量评分 + 模型持久化 (P1 桌面, 优先级见 `CURRENT_STATE.md` 表)**: 现 `run_machine_system` 每次从 telemetry **全量重放**整个生命周期、不落模型 (尽管 `BaselineModel` 本为可序列化 <5KB 设计)。改为: ① 增量 (按 watermark 只评上次之后的新窗, 参考 `acquisition/pg_bridge` 的 `bridge_state` 模式); ② 持久化拟合好的 `BaselineModel` per (机床,系统,epoch,regime) (新表或复用 `phm_v2`), 在线只对新窗打分。这是**实时评分 / 边缘下沉**(引擎持 live 模型, 不每次重导)的前置。可用 FIELD 数据桌面验证。

## 相关
- 评分引擎 → `docs/architecture/algorithm-core.md`
- 回写表结构 → `docs/architecture/data-contract.md` (health_result)
- 看板读取方 → `docs/modules/center-dashboard.md`
