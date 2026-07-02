# CURRENT_STATE.md — 当前状态 (初稿)

> 只记"现在在哪一步、刚做完什么、接下来做什么、有什么坑"。**不记完整历史** (历史进度去 `INTEGRATION_PLAN.md §3` 分阶段)。
> 更新: 2026-07-02。

## 当前开发阶段
**整合期** — 把现场采集系统与算法核合成一套产品。
- 算法核 (`phm_pipeline`): 已验证可用, 回归锚点 + 自检全 PASS, **稳定**。
- 数据契约 (`phm_v2`): 已建表并跑通闭环, **稳定**。
- 正在做: **采集层接入 (首台 OPC UA)** + **中心看板去 mock**。

## 最近完成 (近一两周)
- **边缘网关导向的采集统一入口 / 配置单真相源 [✓ 2026-07-02]**: 首阶段“配置打通”已落地。中心看板采集页保留为统一入口, `phm_v2.acq_config.data.edge` 增加 `mode=edge_gateway`/`gatewayId`/`baseUrl`, v2 工程页可按机床打开对应 WebDashboard 采集工作台; 中心侧继续展示核心状态, 不复制实时曲线调试页。WebDashboard Node API 与 C# collector 默认改读写同一行 `phm_v2.acq_config` (`EDGE_MACHINE_ID` 默认 `FIELD_2026_06_18`), `public.app_config` 只保留 legacy fallback。`/api/config`、NI start/stop/capture、OPC UA start/stop 均落到 `data.control`; Node 每 1s reconcile `control.opcua_run` 与 OPC UA 配置自动启停/重启 poller; C# 轮询 `control.ni_run/capture_seq` 并回写 `ni_state/ni_message/ni_heartbeat/ni_rows/ni_sps/session/capture_done`。WebDashboard 信号目录由 `phm_v2.signal` 生成, 缺配置显示“未建档”。振动数据仍按阶段 1 走 `public.vib_features -> phm_v2.telemetry` 过渡桥, 未改 C# 直写 telemetry。验证: Node 语法检查、中心 v2 JS 语法检查、`dashboard.py` 编译、`regression_anchor`、`smoke_test`、`dashboard_smoke` 全 PASS; C# 构建未能验证, 本机只有 .NET runtime 无 SDK (`dotnet build` 报 No .NET SDKs were found)。
- **看板测试守护 + 部署硬化 [✓ 2026-06-30]**: 接上条硬化的两批纯桌面收尾。① **`server/dashboard_smoke.py`** (DB-free 冒烟, 与现有 smoke 同风格): demo API 契约 (路由/`/api/fleet` demo 标记/全 source=mock/demo 不可写) + 降级 (坏端口 create_app 仍起 → `/api`·`/healthz` 503 degraded, 写 ok:False) + day-mode 语义 (`_calendar_day` 去重 / calendar 跨18天进成熟期·同日 burst 停建立期 / replay 同日进成熟期) — **22 项全 PASS**, 锁住上条全部行为。② **部署硬化**: `dashboard` 默认 **waitress 生产 WSGI** (`--dev` 退 Flask, 未装 waitress 自动退并告警) + `logging.basicConfig` (env `PHM_LOG_LEVEL`) + **`GET /healthz`** 就绪探针 (健康200/DB不可达503) + 连接池上限 8→16 (给 waitress 8 线程留余量); `requirements.txt` 补 `waitress`/`psycopg2-binary`。③ **清掉 `_integration_probe` 4 处明文口令** (a2_seed/a2_show/c1/signal_loader → `default_db()`); 仓库 PHM 侧明文口令归零 (采集子系统 `数控.../` 自带密钥管理, 不在本轮)。验证: dashboard_smoke + regression_anchor **逐位不变** + smoke 全绿。
- **中心看板/评分链路 桌面硬化 (不接真机) [✓ 2026-06-30]**: 四件纯桌面、不依赖真机数据的产品化加固 (鉴权本轮未做)。① **DB 口令去硬编码**: 明文口令散落 3 处 (dashboard/score_runner/pg_bridge) + 文档 → 新建 `phm_pipeline/db_config.py::default_db()` 全走环境变量 (优先级: 环境变量 > `PHM_claude/.env`, 模板 `.env.example`, `.env` 已 gitignore), `PHM_PGPASSWORD` 必填无默认 (缺失清晰报错); `--no-db`/纯算法核无需口令。② **连接池 + overview 单查询**: `DataProvider` 改 `ThreadedConnectionPool(0..8)` + `_cursor` 上下文管理器; `overview` 从 per-(机床,系统) 建连+`_epoch_of` 重复查 (N+1) 收成**一条 `DISTINCT ON` 查询**; 新增 `GET /api/fleet` 聚合 (machines+overview 一次返回, 前端 boot 用它)。③ **出错不静默 mock (仅 demo 保留)**: 生产模式 DB 故障抛 `DBError`→**503 degraded** (前端红色降级条, 不再编造绿灯), 空表→"建立期/无数据" (`source=empty`), mock 仅 `--no-db` 可达; 前端 `#conn` 四态 (在线/演示/降级/离线) + `#sysbar` 横幅。④ **score_runner `--day-mode`** (修复 P4): `calendar`(默认, 诚实跨日) / `replay`(窗序号复现 FIELD burst 演示)。验证: regression_anchor **逐位不变** + smoke/selfcheck 绿; 生产连库 overview/trend/diagnose `source=real` (FIELD 主轴 159 窗 health=0.31); 坏端口→503 degraded; replay `stage3=99` 复现 / calendar 同日停建立期 / 合成跨18天 calendar 进 stage3; `node --check` + py 编译 PASS。详见 `docs/modules/score-runner.md`、计划 `imperative-moseying-panda`。
- **采集子系统增强: 原始数据导出 + 可配置采集页 [✓ 2026-06-30]** (WebDashboard, 子系统内): ① **原始数据导出**(CSV + `#` 注释 JSON 元数据, 供 ML 验证): 抓取原始块 / 特征流 / OPC UA 状态量三类 (`api/src/exportStore.js` + 三路由); 注释行纯 ASCII (防 numpy GBK 编码坑), `pandas.read_csv(comment='#')` 或 `numpy.genfromtxt(skip_header=4)` 直接消费 (真库 round-trip + numpy 实读验证)。② **可配置采集页** `web/index.html`+`app.js`: 写死 5 卡片 → 动态图表网格 (数量自由增删、每图自选信号、统一信号目录覆盖振动特征+OPC UA、time 轴自动对齐多源、布局存 localStorage)。**只加读侧/前端, 未碰任何写库路径** → public 落盘不受影响。详见 `数控.../CLAUDE.md`。对应 INTEGRATION_PLAN B4。
- **采集落库桥 Phase 1 (振动) [✓ 真实库 round-trip 验收 2026-06-30]**: 新增 `phm_pipeline/acquisition/pg_bridge.py` —— 把现场采集器写入的 `public.vib_features` **增量搬进** `phm_v2.telemetry` (HF 特征流), 使"现场采一窗"直接成为 `PostgresSource` 输入, **取代 CSV 回放、闭合 采集→评分**。口径对齐已验证的 `dryrun_build_load`: channel 1..N→signal_id (按 `signal.source_addr` ai 序号派生, ai0→通道1)、5 reducer rms/std/kurtosis/crest/p2p、epoch=current_epoch、regime=NULL。增量 watermark 存新表 `phm_v2.bridge_state`, **写入+watermark 同事务幂等**; 写前按 ts **自动建当月分区** (补 data-contract A3 在桥路径)。**单机假设**: 整张 public.vib_features 归配置的 machine_id。验证 (隔离测试, 全清理): 纯函数离线 + 真库 round-trip —— drain→3窗 written=60→隔离断言(5特征/4信号/每组3/无mean&peak/regime全NULL)→幂等重跑=0→增量+1窗=20→7月窗自动建 `telemetry_2026_07` 分区; `regression_anchor` 数值逐位不变 + `smoke` 全绿。**OPC UA 标量桥 = Phase 2 (缓)**: 阻塞于 PostgresSource 低频窗聚合分支 + rpm 工况分层端到端 (见 P1)。运行: `python -m phm_pipeline.acquisition.pg_bridge --machine FIELD_2026_06_18` 后照常 `score_runner`。
- **算法核审查 + lifecycle 两处修复 [✓ 2026-06-29]**: 深审算法核全模块 (model/score/covariate/lifecycle/regime/engine/config/datasource/nc_profile/score_runner)。**成熟期 PCA+T²+SPE 数学经 regression_anchor 复现确认无误** (full AUC 1.0; weak ablation 带 SPE=1.0 而 diag=0.747/max_abs=0.681, SPE 差异化复现); 参数化限路径 (首台 spindle 走的) 实测 n=60 时 empirical FAR 11.1% vs parametric 0.0%, 选择正确; SPE 抓关系异常放大 90×。修复 lifecycle **两处编排缺陷** (非成熟期数学):
  - **P2 建立期健康度塌缩**: 新机头几条 (n=1,2) pool std≈0 → 标准化爆掉 (|z|~1e12) → health=0 假性红灯。加 `stage1_warmup=5` 守卫 (池太小给中性 1.0)。修后头 5 条 health=1.0 (原 0.0/0.0/0.016)。
  - **P3 成熟期切换台阶**: `blend_lo=50` 远早于 `mature_min_n` (液压 140) → 模型激活瞬间 w3 已 0.6 → 健康度 0.94→0.47 台阶。改混合起点锚 `max(blend_lo, mature_min_n)`, 首条 stage3 样本 w3=0 平滑过渡。修后 selfcheck 原始边界跳变 0.472→0.221 (现 `discontinuous=False` 真过), 健康机 health 0.83→0.91。
  - **P5 自检判据口径收口**: `run_selfcheck` 控制台 PASS 改用**原始**连续性 (原误用 EWMA 平滑版遮掩); P3 修复后原始亦过, 名实相符。
  - 验证: **regression_anchor 数值逐位不变** (成熟期数学未动), run_selfcheck / smoke 全绿, 跨 hydraulic+spindle 两配置确认。**剩余 P1/P4 见「已知风险」, 待真实数据/拍板。**
- **前端架构定 v2 / v1 废弃 [✓ 2026-06-29]**: 拍板前端正式架构 = v2 (方案B master-detail)。`dashboard.py` 根 `/` 改**重定向 `/v2/`** (默认进 v2), 新增 `/v1/` 仅留旧五页平级看板作设计参照 (v1 文件**不删**, 勿再扩展)。验证: test_client headless —— `/`→302→`/v2/`, `/v2/`·`/v1/`·V1 资源全 200。文档同步: `center-dashboard.md` 改写为 v2 IA, INTEGRATION_PLAN §D / 根 CLAUDE 前端行更新。
- **中心看板 v2 重构原型 (方案B master-detail) + 接真实接口 [✓ 桌面验收 2026-06-24]**: 产品设计评审驱动, 新建**独立**原型 `server/static/dashboard_v2/` (index/styles/app, **不动生产 `dashboard/`**)。
  - **IA**: 从"5 平级页"改 master-detail —— 机群列表(汇总+严重度排序+告警原因列) → 机床详情标签(概览/诊断/趋势/维护/运行) → 概览卡**可点下钻**诊断(系统上下文随标签保持) + 大屏分诊 + 设置建档(机床管理/信号映射/采集配置/同步状态) + ⌘K 命令面板; **权限按能力**(读全开放; 写门控=置灰🔒+上报, 非藏页), 修正旧版"只读诊断被藏、reset 对操作工敞开"的反向边界。
  - **设计系统**: 深色令牌(表面明度阶梯 / 语义状态**三重编码**色+图标+文字 / 4px 间距 / 按钮变体 primary·ghost·danger-quiet / 卡片变体 status·alert·interactive·inset)。
  - **诊断条锚定 UCL 绝对标尺 + UCL 虚线**(正常系统条天然短, 越限通道越线=驱动通道); 运行启停按钮随采集态变。
  - **接真实接口**: 适配层把现有 `/api/...` (machines/overview/diagnose/trend/signals/acq-config/collector-status/waveform/alarms + 写 control/signals-CRUD/acq-save/machine-CRUD) 映射进与静态占位**同构**的 DATA/SIGNALS/ACQ/STATUS, **渲染层不变**; 取不到(file:// 直开 或 后端不可达)**回退静态占位**, 顶栏标"在线·真实接口/离线·静态占位"。`dashboard.py` 仅**新增** `/v2/`+`/v2/<path>` 路由(既有路由不动)。
  - **验证**: `--no-db` 起服务 headless 截图 /v2/ 机群+机床详情显示真实 FIELD 数据(在线); file:// 回退静态 4 台(离线); `node --check` + py 编译 PASS。访问: `python -m phm_pipeline.server.dashboard --port 8080` → 浏览器开 `/v2/`。
- **看板工程页交互增强 (5 项) [✓ 桌面验收 2026-06-24]**: ① **删除机床** (`DELETE /api/machines/<id>` + `delete_machine` 事务内连带清 signal/acq_config/health_result/telemetry/vib_raw_blocks + machine; 机床管理加删除按钮 + 二次确认); ② **工程设置顶部机床快捷切换条** (各 tab 共用, 切换即作用当前 tab, 不再回机床管理); ③ 采集控制即在选中机床上操作(并入②); ④ **统一启停** (`set_control target='all'` 一次写同置 ni_run+opcua_run → 消除人工分别点击时间差, 关乎跨源数据对齐) + 保留单独按钮; ⑤ **波形自选** (采集控制加通道下拉, 默认高频/振动通道=按 NI 型号登记, 可自选 → 查看内联走 waveform 真实优先 / 抓取写 `control.capture_signal`)。验证: `__CTLTEST__`/`__HTTPDEL__` 一次性机床全链(统一启停标志/capture带signal/全清删除计数)PASS, `node --check` app.js 语法通过, HTTP 路由+静态 200, 测试机已清。
- **信号映射在线编辑器 [✓ 桌面验收 2026-06-24]**: 工程设置「信号映射」从只读占位 → 可在线编辑 `phm_v2.signal`。后端 `DataProvider` 加 `upsert_signal/update_signal/delete_signal/export_signals/import_signals/clone_signals` + 路由 (`POST /signals`, `PUT|DELETE /signals/<sid>`, `POST /signals/{clone,import}`, `GET /signals/export`); 前端逐条增改删 + 下拉枚举(协议/系统/类型/温度角色)+ **从其他机床克隆**(默认清空地址, 解决"同点位每台 NodeId 不同")+ JSON 导入导出。动机: 用户反馈新建机床后映射界面空白且无绑定入口, 而各台结构/数控系统/OPC UA 模型不同需灵活编辑。验证: `__MAPTEST__` 一次性机床全链(增→改址→克隆FIELD 41信号地址全清→导出42/导入merge42/replace1→删)PASS, FIELD 未受影响; HTTP 路由烟测全 ok; 测试数据已清。**probe 实测确认地址仍占位 (需 live 采集器)**。
- **Phase 2 尾巴: 波形读 vib_raw_blocks + C3 多机床×多系统调度 [✓ 桌面验收 2026-06-24]**: ① dashboard `waveform` 改真实优先读 `vib_raw_blocks` (`_decode_f32` 小端 float32 解码 + 贡献名 `<code>_<feature>` 最长前缀解析→signal_id); 现表空→回退 mock, 阶段B 写块后自动转真值。验证: 解码单元 + 合成块 DB round-trip (插→读 mock=False→删, 可逆) + 空表回退, 全 PASS。② `score_runner` 加 `discover_targets`/`run_all` + `--all`: 各机床 signal 维表 phm_system ∩ CONFIGS, epoch 取各机床 current_epoch, 单 (机床,系统) 失败隔离。验证: FIELD 发现 (hydraulic no-op 0 / spindle 159·stage3 99), `--all` 幂等写 159; smoke PASS。
- **diagnose 去 mock / 评分回写 Phase 2 [✓ 真实数据端到端验收 2026-06-24]**: `BaselineModel.explain()` 输出 T²/SPE/UCL + 逐特征贡献 (精确可加分解: SPE 贡献=残差平方和=SPE, T² 贡献=z·Dz 和=T²) → 经 `LifecycleResult`/`HealthResult` 透传 → `score_runner` UPSERT 补写 `t2/spe/ucl_t2/ucl_spe/contributions(JSONB)` 五列 → dashboard 新增 `_real_diagnose` 真实优先, 诊断页每通道画 T²(蓝)+SPE(黄高亮)双条。验收: FIELD 主轴 stage3 共 99 行五列全落值, `/api/.../diagnose` source=real, SPE top3 点出关系型异常驱动通道; explain 分解自检/regression_anchor/smoke/HTTP 全 PASS。
- **评分回写闭环 Phase 1 [✓ 真实数据端到端验收]**: 新建 `phm_v2.health_result` 表 + `score_runner.py` (telemetry → `HealthEngine` → UPSERT health_result, 看板显示字段评分侧算好) + dashboard overview/trend 改读真值 (空表回退 mock)。验收: FIELD_2026_06_18 主轴 159 窗振动特征回放, 走完建立期→成熟期(真实 PCA+T²+SPE), 末窗 health=0.31/黄灯; `/api/overview`+trend `source=real`; regression_anchor/smoke PASS。
- **phm_v2 数据契约 [✓]**: machine/signal/telemetry(月分区)/vib_raw_blocks 建表; 159 窗写入→读回→过模型, 与直算逐窗差 2.11e-15。
- **signal 维表填全 [✓]**: 首台 41 信号 (4 振动 + 主轴8 + 进给18 + 液压11 bool)。三发现见下「已知风险」。
- **成熟期门槛压缩 [✓]**: 参数化 UCL (T²~F + SPE~Jackson-Mudholkar), 主轴压到 ~5p, 液压代理验证进成熟期 46→23 天, 去抖 FAR 仍 0%。
- **中心看板响应式五页骨架 [✓]**: `server/dashboard.py` + `static/dashboard/` (手机/平板/桌面/大屏四档断点), 含采集配置/控制 tab (对齐线B `app_config`)。
- **采集层共享件 [✓ desk]**: `signal_loader.py`(真实库 37 OPC UA 信号验证) + `telemetry_writer.py` + `protocol.py` + `nc_profile.py`(NC 空跑=regime 定义源)。

## 当前任务 / 下一步候选 (优先级排序, 2026-07-02 综合)
> 下一条线**待用户拍板**。下表把"硬化批次的遗留待做"与"原有候选/风险"**横向比较**后分档。
> 判据: ① 是否阻塞上真机/正确性·安全 ② 是否纯桌面可推 (无需真机即可做+验证) ③ 产品化杠杆。

| 档 | 待办 | 桌面/真机 | 工作量 | 为何此档 (横向比较) |
|---|---|---|---|---|
| **P0 上真机前必堵** | **rpm 工况分层端到端接通** (=风险 P1 高) | 接线桌面+合成验证; 真值需多档真机 | 中 | 不做则真实多 rpm 数据**静默池进同一基线** (违反"同工况才能比", UCI 实测 FAR 可达 93%) → 后续所有"接真机展示"都建在被污染基线上, 故高于一切功能项 |
| **P0 上真机前必堵** | **写接口鉴权 + CORS 收紧** (security) | 纯桌面 | 中 | 本轮按用户意见暂缓; 但 `DELETE`/写接口当前全裸奔 (权限仅前端置灰), 多机内网部署前必做。与 rpm 并列: 二者都是"上真机的前置闸门" |
| **P1 纯桌面可推** | **score_runner 增量评分 + 模型持久化** | 纯桌面 (FIELD 可验) | 中–大 | 现每次全量重放、不存模型 (模型本为可序列化 <5KB 设计, 未用上)。实时评分 / 边缘下沉的前置。**杠杆最高的桌面项**: 不依赖真机即可推进且解锁实时路径 |
| **P1 纯桌面可推** | **前端详情懒加载** | 纯桌面 | 中 | 首屏请求 N×10→1 (后端 N+1 已修, 这是前端那半)。撑多机规模的收尾 |
| **P2 需真机/真实数据 (阶段 B/E)** | 主轴稳态门控启用 | 需 steady 通道真机数据 | 中 | 与 rpm 同根 (steady_channels=() 未接); 排高振瞬态窝进池。等真机 |
| **P2 需真机/真实数据** | OPC UA poller B2 + 低频窗聚合 | 需 live Node 采集器/真机 | 中 | 喂主轴标量/rpm; 启用 PostgresSource 低频分支 |
| **P2 需真机/真实数据** | `/api/sync` 边缘入库 | 桩可桌面填; 运营意义需真边缘 | 中 | store-and-forward 闭环; 真正的边缘/中心分离前置 |
| **P3 低 / 杂项** | selfcheck 判据口径统一 (=风险 P5 低) | 纯桌面 | 小 | 名实一致, 不影响结果 |
| **P3 低 / 杂项** | 采集子系统 `数控.../` 残留明文口令清理 | 桌面 | 小 | 独立子系统 (自带 `api/.env`/`COLLECTOR_PGPASSWORD`); 单独一轮 |

> **建议下一步**: 续纯桌面 → 先 **P1 `score_runner` 增量+模型持久化** (杠杆最高, 解锁实时); 准备上真机 → 先堵 **P0 rpm 分层 (+ 鉴权)**。
> 已完成项见「最近完成」; 阶段 E 现场标定见文末。权威分阶段计划见 `INTEGRATION_PLAN.md` (§3 阶段 / §4 待确认)。

## 已知风险 / 坑
- **[算法核审查 2026-06-29] rpm 工况分层端到端未接通 (P1, 高)**: spindle `baseline_by=("rpm_bin",)` 但 `regime_bins={}` 空、`PostgresSource` 写 `condition["regime"]` 而非 `rpm_bin`、`nc_profile.to_c2_regime()` 未被 `score_runner` 合并 → 实测只生成单 regime `(None,)`。真实多 rpm 数据会**静默池进同一基线** (违反"同工况才能比"锁定约束, UCI 实测 FAR 可达 93%)。**接多档真实数据前必须接通** (合并 nc_profile 或 `baseline_by` 改读 regime 列, 待拍板)。与下条「稳态门控未启用」同根 (steady_channels=() 亦未接)。
- ~~**[算法核审查 2026-06-29] stage3_min_days 被计数器架空 (P4, 中)**~~ **[✓已修复 2026-06-30]**: `score_runner` 加 `--day-mode calendar(默认)|replay`; calendar 取 rec 时间戳日历日 (`n_days` 计真实跨日, 门槛生效), replay 保留窗序号复现 FIELD burst 演示。复现 FIELD stage3 须带 `--day-mode replay`。
- **[算法核审查 2026-06-29] selfcheck 连续性判据口径 (P5, 低)**: docstring 称判据=原始 `continuity.discontinuous`, 控制台 PASS 实际用 EWMA 平滑版 (CSV 仍记原始)。P3 修复后原始亦过 (0.221<0.285), 当前不再遮掩; 但口径应统一 (控制台如实报原始, 或文档写明判据=EWMA)。
- **稳态门控对 vibration-only 数据未启用**: 当前回放是 2.5min 连续标定数据, 无 steady 通道 → 高振瞬态窝进基线池 → 健康偏低偏噪。这是"真做基线只取稳态窗"的忠实反映, **非 bug**; 真上线需 NC 空跑标记 + 稳态门控。
- **数据节奏是标定 burst, 非真实事件节奏**: runner 按窗序当事件样本回放 (day=窗序), 证明管路通、数值真实; 分期的运营意义需真实事件节奏数据 (阶段 E)。
- **首台 signal 维表三发现**: ① 成对轴 X1/X2·Y1/Y2·B1/B2 **共用同一 OPC UA 地址** → 冗余, 进给做基线前必须 probe 实测确认; ② **液压只有 bool 压力**, 无连续压力/流量 → 这台做不了 UCI 式液压效率基线, 液压退化为 L1 状态标志位; ③ **主轴信号最全** → 故首台落地主系统 = **主轴** (非"液压先行", 旧文档此处已过时)。
- **文档陈旧点**: `PHM_claude/PROJECT_STATUS_AND_HANDOFF.md` (2026-06-16) 与 memory 索引仍写"液压先行/第一个落地系统", 已被"主轴先行"取代; 重构时应在 archive 注明。

## 现场标定待办 (阶段 E, 需用户/真机)
物理限 L1 / 稳态段匹配热机程序 / 工况分层粒度标定 / 大修 reset 流程 / 存量机退化验证 (用户确认精度)。
