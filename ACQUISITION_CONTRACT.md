# 采集层契约与 NC 空跑框架 — 全貌

> 这是**采集层的单一参考**: 多协议/多硬件怎么接、数据怎么落库、工况(regime)怎么定义。
> 上层入口仍是 `CLAUDE.md`; 算法核见 `PHM_claude/PROJECT_STATUS_AND_HANDOFF.md`; 整合计划见 `INTEGRATION_PLAN.md`。
> 更新: 2026-07-03 (加 §4b 采集落库桥, §4c phm_v2.acq_config per-machine 配置/控制契约)。

## 0. 一句话

**傻采集器(各协议/各语言各写各的)只负责把读数写进 `phm_v2.telemetry`; PHM(Python)统一从 telemetry 消费做工况分层/稳态门控/评分。** 多协议的接缝是**数据表**, 不是代码接口。

## 1. 多协议主接缝 = telemetry 表 + signal 维表 (关键认知)

- `phm_pipeline/acquisition/` 是 **NC-Link 这一种协议的瘦采集器**, 不是通用采集层。
-  一种协议/硬件 = **写一个瘦采集器(任意语言)写 telemetry + 在 `signal` 维表登记几行**, 不碰已有代码。
- 各路状态: 首台**西门子840D 走 OPC UA**(线B Node 采集器) + 高频振动**NI-DAQmx 走 C# native**(就地算特征) + 后续台份可能**华中HNC/发那科FANUC 走 NC-Link/FOCAS** + 国产振动传感器各自驱动。能力不同(NC-Link 只有寄存器轮询、无高频波形)。

## 2. 数据契约 (`phm_v2`, 建表见 `_integration_probe/phm_v2_schema.sql`)

- **`signal`** (信号定义维表 = 权威登记): `code`/`protocol`(nclink|opcua|ni_daq)/`source_addr`/`phm_system`(feed|spindle|hydraulic)/`signal_kind`(vibration|current|speed|position|temperature|pressure|bool)/`temp_role`(**confound**|**coupled**|NULL)/`regime_role`(bool)/`is_high_freq`(bool)。**每台机床各自定义, 不假设统一通道集。** 首台已登记: 4 振动(ni_daq) + 37 OPC UA 标量。
- **`telemetry`** (标量遥测长表, 按月分区): `(machine_id, signal_id, ts, value, feature, epoch, regime)`。`feature=NULL`=原生标量读数(PostgresSource 现场 reduce); `feature=rms/std/...`=振动窗特征(采集端就地算)。
- `vib_raw_blocks`(事件/手动原始波形); `health_result`(PHM 回写, 待上前端再建)。

## 3. signal 维表 → 采集映射 (`acquisition/signal_loader.py`) ✓

把 `signal` 维表直接转成采集映射, 采集映射不再手填、与 DB 一致 (消除双真相源)。**角色映射规则**:

| signal 行 | → ChannelEntry.role | 含义 |
|---|---|---|
| `regime_role=TRUE` | `condition` | 转速/档位等工况分层键 |
| `temp_role='confound'` | `confounder_temp` | 混淆温, 回归剔除 |
| `temp_role='coupled'` | `channel` | 耦合温, 进特征向量 |
| `signal_kind='bool'` | `condition` | 液压 bool 状态位, **不进 PCA 向量** |
| 其余(current/speed/pressure/coupled温) | `channel` | 进特征向量 |
| `is_high_freq=TRUE`(振动) | **跳过** | 走 NI/C# 采集器直写 telemetry, 不轮询 |

接口: `signals_to_mapping(rows,...)`(纯函数) / `load_mapping(conn, machine, protocol)` / `load_signal_ids(...)`。
**已对真实库验证**(`_integration_probe/signal_loader_telemetry_check.py`): FIELD_2026_06_18 的 37 OPC UA 信号 → condition 13 / channel 14 / confounder_temp 10。

## 4. telemetry 写入契约 (`acquisition/telemetry_writer.py`) ✓

瘦采集器→telemetry 的**行格式范本** (非 Python 采集器照此行形状写库):
- 低频标量轮询: 每采样点一行, `feature=NULL`。
- 高频振动: 每窗特征一行, `feature=rms/std/kurtosis/...`。
接口: `record_to_rows(rec, signal_ids, machine_id, epoch, regime)`(纯函数) / `TelemetryWriter.write_record(...)`(惰性 psycopg2 批量写)。
闭环: 瘦采集器 → `TelemetryWriter` → telemetry → `PostgresSource` → CollectionRecord → 特征 → `HealthEngine`。

## 4b. 采集落库桥 public → phm_v2 (`acquisition/pg_bridge.py`) ✓ [Phase 1 振动, 2026-06-30]

现状: WebDashboard 采集器(C#/Node)实时写 **public** 旧表(`vib_features`/`_OPCUA_*`), 算法核读 **phm_v2**。两系统**同库 (`vibration_db`) 不同 schema**。在 C# 采集器尚未直写 telemetry(B1 终态)前, 用**过渡桥**把 public 搬进 `phm_v2.telemetry`:
- **Phase 1 (振动, 已落地)**: `public.vib_features` → `telemetry`(HF 特征流)。channel 1..N→signal_id 按 `signal.source_addr` 的 NI ai 序号派生(ai0→通道1); 5 reducer rms/std/kurtosis/crest/p2p; epoch=`machine.current_epoch`; regime=NULL。增量 **watermark** 存 `phm_v2.bridge_state`, **写入+watermark 同事务幂等** (只导 time>last_ts); 写前按 ts **自动建当月分区**(补 A3 于桥路径)。**单机假设**: 整张 public.vib_features 归配置的 machine_id (单采集器=单机; 多机需按 session 绑定改造)。
- **Phase 2 (OPC UA 标量, 缓)**: 阻塞于 `PostgresSource` 低频窗聚合分支 + rpm 工况分层端到端(见 §8 / INTEGRATION_PLAN P1)。
- **终态**: C# 采集器直写 telemetry(B1), 桥退役。
口径对齐已验证的 `_integration_probe/dryrun_build_load.py`。真库 round-trip 验证(隔离测试全清理): drain→3窗 written=60→隔离断言(5特征/4信号/每组3/无mean&peak/regime全NULL)→幂等重跑=0→增量+1窗=20→7月窗自动建 `telemetry_2026_07` 分区; `regression_anchor` 逐位不变 + `smoke` 全绿。
运行 (PHM_claude/ 下): `python -m phm_pipeline.acquisition.pg_bridge --machine FIELD_2026_06_18` (`--dry-run`/`--reset-watermark`), 随后照常 `score_runner`。

## 4c. 配置/控制契约 (`phm_v2.acq_config`) ✓ [Phase 1 配置单真相源, 2026-07-02]

首阶段把“采集项”和“采集参数/控制”收口到 `phm_v2`, 但暂不改变振动数据落库路径:
- **采集项权威 = `phm_v2.signal`**: WebDashboard 信号目录、OPC UA NodeId、NI 通道、系统归属、信号类型、工况/温度角色、高频标记均从这里生成。缺少登记时 UI 显示“未建档”, 不再把硬编码 catalog 当集成默认。
- **采集参数/控制权威 = `phm_v2.acq_config.data`**: per-machine JSONB, 默认由边缘进程环境变量 `EDGE_MACHINE_ID` 选中机器 (`FIELD_2026_06_18`)，也可由 Web/API 请求的 `machine_id` 显式选择。`public.app_config` 只作 legacy fallback, 不再是集成默认路径。
- JSON 顶层约定: `edge{mode,gatewayId,baseUrl}` / `acquisition{source,rate,samplesPerChannel,inputBufferSize,tableBaseName,featureWindowSamples,event*,channels[]}` / `opcua{enabled,profile,endpoint,anonymous,user,pw,pollIntervalMs}` / `nclink{...}` / `control{ni_run,opcua_run,capture_seq,capture_signal,ni_state,ni_message,ni_heartbeat,ni_rows,ni_sps,session,capture_done,...}`。
- WebDashboard Node `/api/config`、`/api/opcua/catalog`、OPC UA NodeId 保存、启用集合保存、OPC UA start/stop、NI start/stop/capture 均以当前 `machine_id` 为作用域读写对应机床 JSONB；中心看板 `/api/machine/<id>/acq-config|collector-status` 读取同一配置并只展示入口/状态/摘要。
- Node API 每 1s reconcile `control.opcua_run` 与 OPC UA 配置签名, 自动启动/停止/重启 poller; WebDashboard 本地按钮只是改同一控制位。当前 poller 为单实例, 定时 reconcile 跟随最近一次带 `machine_id` 的工作台/API 请求; 同一边缘进程同时采多机需后续 per-machine poller。
- C# collector 读取 `data.acquisition` 和 `control.ni_run/capture_seq`, 并把 `ni_state`/`ni_message`/`ni_heartbeat`/`ni_rows`/`ni_sps`/`session`/`capture_done` 回写到同一 JSONB。
- `data.edge.baseUrl` 是中心看板跳转 WebDashboard 边缘工作台的入口; 中心生成入口时追加 `?machine_id=<machine_id>`，避免多机共用同一边缘地址时读到默认机床配置。中心侧只展示核心状态、信号摘要和采集参数摘要, 实时曲线/调试/NodeId/启用集合仍在 WebDashboard。
- 安全边界: 科研首阶段未做鉴权/CORS/审计; 服务应绑定本机或内网, 不得直接暴露公网。删除机床、epoch reset、停止采集等破坏性操作保留二次确认。

数据路径仍按 §4b: C# 振动特征继续写 `public.vib_features`, `pg_bridge.py` 增量搬到 `phm_v2.telemetry`; OPC UA 标量入 telemetry 与 rpm/regime 分层属于 Phase 2。
## 5. Python 侧协议客户端接口 (`acquisition/protocol.py`)

仅服务"用 Python 同一套 `Collector` 轮询逻辑"采的协议: 实现 `ProtocolClient`(get_value/set_value/probe/ping/get_model)即可复用分窗/补眠/组装 record。`make_client(protocol, conn)`: nclink 已实现; opcua/focas 抛 `NotImplementedError` 并指明落地路径。`ChannelEntry.protocol` 标签使一份映射可混标协议。

## 6. NC 空跑程序 = regime 的定义源 (`nc_profile.py`) ✓

**regime 不凭空设阈值, 由机床暖机/空跑跑的标准 NC 动作程序定义** —— 程序里每个"设定转速/进给→待稳→驻留测量"节点 = 一个 regime 采样点。`IdleRunProfile` 是单一定义源, 同时驱动:
1. **生成空跑 G代码** (FANUC/SINUMERIK 840D/HNC 方言; M码标记/G04 驻留单位待现场坐实);
2. **派生 C2 配置**: `to_c2_regime()` → `baseline_by` + `regime_bins`(**档边界=相邻设定点中点**, 用设定值非实测值分箱, 无歧义);
3. **稳态测量标记**: 每驻留段起止发标记。

**稳态门控两层** (回答"阈值=程序转速达成节点?": 是):
- **程序标记(权威)**: `settle_s` 后进入 `dwell_s` 驻留段即稳态窗, regime 由设定值给定;
- **信号门控(核验/兜底, `regime.SteadyGate`)**: 实测 vs 设定容差 + CV/漂移; 无程序的有机运行只靠此层。

**机型一致性**: profile 按 `machine_type`(车/铣/镗)给默认值, 台份覆写 → **同类机床共用 profile, 采集分层天然一致**。预设 `mill_v1/lathe_v1/boring_v1`。

## 7. 模块清单与状态

| 模块 | 职责 | 状态 |
|---|---|---|
| `acquisition/nclink_client.py` | NC-Link HTTP 客户端 + Mock | ✓ 现场验证 |
| `acquisition/channel_map.py` | 通道映射(含 protocol 标签) | ✓ |
| `acquisition/collector.py` | 轮询一窗→CollectionRecord | ✓ |
| `acquisition/model_file.py` | 解析 NC-Link model.json | ✓ |
| `acquisition/protocol.py` | `ProtocolClient` 接口 + 工厂 | ✓ desk |
| `acquisition/signal_loader.py` | signal维表→采集映射 | ✓ desk+真实库 |
| `acquisition/telemetry_writer.py` | record→telemetry 行 + 写库 | ✓ desk (纯逻辑) |
| `acquisition/pg_bridge.py` | public.vib_features→telemetry 振动桥 (watermark 幂等 + 自动建分区) | ✓ 真库 round-trip (见 §4b) |
| `nc_profile.py` | 空跑 profile→G代码/C2/稳态标记 | ✓ desk |
| `regime.py` / `engine.py` | C2 稳态门控/工况分层 + 健康引擎 | ✓ desk (见 INTEGRATION_PLAN C2) |

desk 验证脚本(`_integration_probe/`): `signal_loader_telemetry_check.py` / `nc_profile_and_protocol_check.py` / `c2_engine_desk_check.py`。

## 8. 待办 / 待现场标定

- NC 程序方言落地: FANUC/西门子840D/华中 的真实 **M码标记 / G04 驻留单位 / PLC 输出位**, 并与采集时间戳同步。
- 稳态门控阈值(`steady_max_cv`/`slope`)、rpm 档边界、混淆温通道名、信号名→regime 标量归一: 待首台真实数据。
- `TelemetryWriter` 真实写库压测; 分区自动建(A3) **桥路径已做** (`pg_bridge._ensure_partitions` 写前按 ts 建当月分区), NC-Link `TelemetryWriter` 可复用同逻辑(待)。Python OPC UA 客户端(若要复用 Collector, 否则用线B Node)。
- 低频原始序列窗聚合分支(PostgresSource)启用 = OPC UA 标量桥(pg_bridge Phase 2)的前置。




