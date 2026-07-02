# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
> 这是整个项目的**单一入口**: 只读本文件即可理解"项目要做什么、现状、关键决策、怎么开发"。
> 更深的分支文档见末尾「文档索引」。更新: 2026-06-22。

## 沟通约定

- **全程中文输出。**
- **先讨论再探索**: 概念/需求先厘清, 由用户提供接口与协议文档, 不要自主大范围探索或直接写代码。改动前先对齐。

---

## 一、项目要做什么 (全貌)

重型机床 (进给 / 主轴 / 液压三系统) **健康基线系统**。一句话: **"这台机床现在还正常吗"**。
- 核心是**异常检测** (One-Class: 只有健康数据, 故障样本稀缺), 趋势为附带价值; **不做** RUL/剩余寿命预测, **不以**故障定位为主线。
- 方法是**自基线**: 机床与自己的过去比, 大修/拆装后 reset 基线 (跨 reset 不可比)。无同型号参考机, 靠存量设备的客观退化 + 人工大修 reset + 用户确认精度作外部锚点。
- 成熟期算法已锁定且验证: **PCA + T² + SPE** (见下「关键约束」)。

**这个项目当前的主任务 = 把"现场采集系统"与"健康算法核"整合成一套完整产品**:
- 采集系统 (`数控机床数据采集与状态监测系统/`) 负责把机床数据采下来落库, 自述"只做采集落库、不做报警"。
- 算法核 (`PHM_claude/phm_pipeline`) 负责健康判定、告警、生命周期、操作工界面。
- 两者天生互补; 整合的数据契约边界 = PostgreSQL `vibration_db` 的新 **`phm_v2`** schema (见「三、整合」)。

**部署现实 (决定设计形态, 重要)**:
- **首台部署设备走 OPC UA** (Siemens 840D; 节点见 `数控机床数据采集与状态监测系统/OPCUA地址对照.xlsx`): 主轴/各轴 电流·温度·速度 + 油压 bool + NI-DAQmx 高频振动。
- **后续台份可能走 NC-Link, 且数据种类/数目/采集地址都不一定相同。** → 系统**不得假设统一的固定通道集**; 每台机床用自己的 `phm_v2.signal` 维表定义信号, 多协议并存且预留接口 (新协议=新写一个瘦采集器+signal 登记)。

## 子目录角色

工作目录 `D:/Proj/PHM_realtest`:
- `PHM_claude/` — **算法与产品主线** (Python/numpy)。健康算法核 + 采集控制台。产品代码在 `phm_pipeline/` 包内; `step1-9*.py` 与各 `*_validation_plan.md` 是**试验/验证脚本, 非产品**, 整合时不并入。
- `数控机床数据采集与状态监测系统/` — C#(NI 振动) + Node(OPC UA) + Web 看板的**采集落库系统**, 自带 `CLAUDE.md`。现为**首台 OPC UA 采集的事实来源**, 不再是"一般不动"。
- `CNCDataGet/` — 现场已验证的 NC-Link 寄存器轮询采集器 (Python), NC-Link 接入的事实依据 (`model.json`/轮询接口)。后续 NC-Link 台份会用到。
- `_integration_probe/` — 整合期临时分析件 (导出 CSV / 连通脚本 / schema 设计稿 / 建表 SQL), 非产品, 可清理。

---

## 二、PHM_claude 算法核 (产品主线)

数据流, 采集层与算法层解耦——**换采集源只换 DataSource, 上层不动**:

```
DataSource → CollectionRecord → [regime标注·稳态门控] → segment → features → covariate
→ model(训练) / score(在线) → alarm → lifecycle⟲(每regime) → engine汇总 → selfcheck(report)
```

**离线算法核** (`phm_pipeline/*.py`, 纯 numpy / SVD / pinv):
- `datasource.py` — 解耦点。`CollectionRecord` 契约 (含 `precomputed` 预算特征字段, 供高频振动) + `FileSource`(回放 UCI)/`MockSource`/`RealSource`(NC-Link 采集器)/`PostgresSource`(读 phm_v2.telemetry)。
- `model.py` — `BaselineModel` = 标准化 + PCA(SVD) + T² + SPE; UCL 标定 `ucl_method`: 样本外经验分位(默认, 锚点用) / 参数化(T²~F + SPE~Jackson-Mudholkar, 小样本稳, 用于压成熟期门槛) / auto; 可序列化(<5KB); `RegularizedCovModel` 兜底。
- `score.py` — `health = exp(-3·max(T2/UCL_T2, SPE/UCL_SPE))` + T²/SPE 特征贡献分解。
- `alarm.py` — `AlarmState`: 双层告警 (L1 物理限 ∥ L2 模型) + EWMA + K连续去抖。
- `lifecycle.py` — `LifecycleManager`: 三阶段 (n<30 工程先验 → 分位评分 → 成熟期 PCA+T²+SPE), 混合过渡, 成熟期 `score>1` 样本**不准入基线** (防故障污染); 阶段阈值/UCL法随 config 可调 (主轴压缩档门槛~5p + auto 参数化限)。
- `regime.py` — **C2 工况层**: `SteadyGate` 稳态门控 (非稳态不准入基线) + `RegimeLabeler` 工况标量分箱 (rpm档)。缺省不门控/不分箱。
- `engine.py` — **C2 健康引擎**: 多 regime 在线消费 (标注→门控→特征→混淆温残差化→每 regime 一套 lifecycle) → `HealthResult`; 混淆温空时退化为单 lifecycle (逐点复现 selfcheck)。
- `nc_profile.py` — **空跑 NC 程序框架**: idle-run profile = regime **单一定义源**, 同时派生 C2 `regime_bins`/`baseline_by` + 生成空跑 G代码 (FANUC/西门子/华中方言) + 定义稳态测量标记; 机型预设 车/铣/镗。稳态门控两层: 程序标记(权威, =settle 后驻留段) + 信号 CV 核验/兜底。
- `covariate.py` — `TempResidualizer` 混淆温度回归剔除 (含热态: 主轴热态作协变量非分层)。
- `config.py` — `SystemConfig` + `hydraulic_v1()` + `spindle_field_v1()`(现场 4 振动测点, 每点 rms+kurtosis+crest=p12, 压缩档 ucl_method=auto/门槛~5p/按 rpm 分层); 进给占位; `mature_min_n=max(stage2_max_n, ratio·p)`。

**采集控制台 (边缘侧)** (`phm_pipeline/acquisition/` + `store/` + `server/app.py`): NC-Link HTTP 客户端 + 通道映射 + 轮询采集 + SQLite 落库 + Flask/WS 单页控制台。注: 这是 **NC-Link 这一种协议的瘦采集器**, 非通用采集层。**多协议主接缝 = `telemetry` 表 + `signal` 维表 (各协议各写瘦采集器, 任意语言); `acquisition/protocol.py` 正式化 Python 侧 `ProtocolClient` 接口 + `make_client` 工厂——加协议=实现该接口(复用 Collector)或独立瘦采集器写 telemetry。** `signal_loader.py`(signal维表→采集映射, 已对真实库 37 OPC UA 信号验证) + `telemetry_writer.py`(record→telemetry 行格式范本+写库) 已通。**采集层全貌(多协议契约/signal映射/telemetry写入/NC空跑profile↔regime)详见 `ACQUISITION_CONTRACT.md`。**

**中心健康看板 (中心侧)** (`server/dashboard.py` + `server/static/dashboard/`): 读 phm_v2 → 响应式五页富前端(纯原生无CDN, 手机/平板/桌面/大屏)。
- 五页: 总览(健康灯+建立期x/N+告警条) / 系统诊断(T²·SPE贡献+原始波形) / 维护·基线(epoch·reset) / 趋势·历史(SVG折线) / 工程设置(多tab)。
- **工程设置整合线B采集**: 信号映射(signal维表) / 采集配置(NI采样率·通道·灵敏度·落盘 + OPC UA + NC-Link, 写 `phm_v2.acq_config`) / 采集控制(OPC UA·NI 开关·抓取·心跳) / 同步·状态。
- 接口: `/api/status`(数控HMI投影) + `/api/sync`(边缘同步) + machine/<id>/{acq-config,control,collector-status,waveform,alarms}。健康数值与采集器状态当前 mock, 真实数据/采集器(阶段B/C)接入后填实。运行 `python -m phm_pipeline.server.dashboard --port 8080`。

**开发命令** (在 `PHM_claude/` 下运行):
```bash
python -m phm_pipeline.regression_anchor   # 验证算法核复现 step7-9 数值 (改算法核后必跑)
python -m phm_pipeline.run_selfcheck       # 端到端自检 (回放 UCI 液压)
python -m phm_pipeline.smoke_test          # 模块组合冒烟
python -m phm_pipeline.server.app --mock   # 采集控制台 (无硬件演示)
```
没有 lint/CI; "测试" = 上面三个自检脚本 + 控制台 `server/e2e_mock_test`。**改算法核优先跑 `regression_anchor`**。

---

## 三、整合: 采集系统 × 算法核 (当前主战场)

详见 `INTEGRATION_PLAN.md` (权威开发计划/分阶段步骤/待办)。已拍板:

| 议题 | 结论 |
|---|---|
| 数据契约边界 | `vibration_db` 新建 **`phm_v2`** schema, **直接作生产**, public 旧空表废弃 |
| 采集协议 | NC-Link + OPC UA **并存且预留接口** (首台 OPC UA, 后续可能 NC-Link 异构) |
| 界面 | **合并到 Web 端** (不做数控原生 HMI, 避免逐系统适配); 五页 + 操作工红绿灯 + 建立期方案 A |
| 合并范围 | 只取 PHM 产品形态 (`phm_pipeline` 包); 试验脚本不并 |

**phm_v2 数据契约** (长表 + 维度表, 新机型/新协议只加数据行不改表):
- `machine` (机床维表: SN/数控系统/`current_epoch` 大修 reset)
- `signal` (信号定义维表 = channel_map 的库版: `protocol`/`source_addr`/`phm_system`/`signal_kind`/`temp_role`(混淆/耦合)/`regime_role`/`is_high_freq`) ——**每台机床各自定义, 不假设统一通道集**
- `telemetry` (标量遥测长表, **按月分区**: machine_id/signal_id/ts/value/`feature`/epoch/regime) —— OPC UA/NC-Link 标量(feature=NULL) 与振动窗特征(feature=rms…)统一
- `vib_raw_blocks` (事件/手动原始波形 float32 块); `health_result` (PHM 回写, 待上前端再建)

**采集层架构骨架** (已确认): **傻采集器(多语言保留)写 telemetry + Python/PHM 统一做工况/稳态/评分**。
- 高频振动 (25.6kHz) 必须 C# native (NI-DAQmx), 特征**就地算**写 telemetry; 低频标量轮询写原始读数。
- 工况 `regime` 标注/稳态门控/评分/基线准入**集中在 Python 层** (regime 是跨源逻辑: 工况来自标量通道, 要按时间戳给振动打标)。

**部署形态**: 事件性数据(交班/热机后, 非连续) + 断网 → **边缘 store-and-forward + 中心只读富前端**。边缘(每机床)采集+评分+本地SQLite缓冲+驱动数控HMI简略界面+联网同步; 中心内网服务器只读服务响应式富前端(平板/手机iOS安卓/办公)+综合大屏(领导展示)。代码按"引擎/前端可分离"写: `server/app.py`(NC-Link控制台)≈边缘侧, `server/dashboard.py`(只读看板)=中心侧。

**整合进度**: A1(建phm_v2+干跑闭环) ✓; C1(`PostgresSource` 读telemetry→健康曲线, 与直算差1e-15, 算法核回归PASS) ✓; A2(据 OPCUA地址对照.xlsx 填 signal 维表, 41信号; 发现成对轴共址/液压仅bool/主轴信号最全) ✓; D1+D2(中心看板 `server/dashboard.py` + 响应式五页骨架 `static/dashboard/`, 手机/平板/桌面/大屏四档断点, mock数据) ✓。详见 `INTEGRATION_PLAN.md`。

---

## 四、关键约束与坑 (来自验证, 勿踩)

- **算法路线已锁**: 成熟期必须 PCA+T²+SPE。**SPE 不可省**——关系型异常 (各通道边际正常、耦合关系变了) 是本方案相对传统单变量阈值的唯一差异化价值 (单变量/对角 AUC≈0.5, 带 SPE AUC≈1.0)。现场 4 振动测点 (3 箱体+1 前轴承套) RMS 相关 0.98–1.00, 正是 SPE 的用武之地。
- **温度分两类角色**: 混淆温度 (环境/电机) 回归剔除; 耦合温度 (轴承/油温) 进特征向量。作用相反, 别混 (落到 `signal.temp_role`)。
- **工况分层 = 诊断分辨率旋钮**, 取"满足诊断需求的最粗分层"。同工况内才能比, 跨工况污染基线 (UCI 实测 FAR 可达 93%)。已定: 液压单基线 / 主轴 rpm档 (热态=协变量, 不分层: 效应平滑可残差化, 且"热机后采"协议已标准化热态) / 进给 轴×方向×速度档。**rpm 强非线性→分层; 热态平滑→协变量**, 别混。NC 程序扫 rpm 各箱并行填充, 分层不再是日历瓶颈。
- **振动能力来自 NI-DAQmx 高频采集** (C# 采集系统), 不是 NC-Link——NC-Link 只有寄存器轮询无波形, 拿不到高频振动。两条采集路能力不同。
- **现场实测振动高度非平稳** (RMS 0.5g→25g 含瞬态): 真做基线必须**只取稳态窗**, 原始整段不能直接当健康池 (整合稳态门控在 Python 层补)。
- **跨 reset 不可比**: 综合健康分只在一个 epoch 内有效。维护好坏不看综合分, 看绝对裸指标台阶 + 维护后稳定性。
- **旧文档已过时**: `cnc_health_baseline_technical_plan.md` (5月) 的对角 T²/温度一律剔除已被 step7-9 推翻。以 `PROJECT_STATUS_AND_HANDOFF.md` + step7-9 + 本文件为准。

## 五、当前阶段

- **算法核**: `phm_pipeline` 已验证可用 (回归锚点 + 自检全 PASS)。新增参数化 UCL + 成熟期门槛压缩 (主轴 ~5p): 液压代理验证进成熟期由 46→23 天减半、去抖 FAR 仍 0%; 主轴特征裁剪 p20→12 (砍共线 std/p2p)。这把首台主轴早期成熟期压到 ~2.5–5 周, 装得进安装验收/跑合窗口。
- **整合**: phm_v2 数据契约已建并验证, PHM 侧消费路径 (PostgresSource) 已通。正推进采集层接入 (首台 OPC UA)。
- **产品/界面**: 中心看板响应式五页骨架已搭 (`server/dashboard.py`, mock 数据驱动); 待接真实 health_result 去 mock、复用线B ECharts 做密集趋势、数控HMI简略界面落地。

## 六、文档索引

- `INTEGRATION_PLAN.md` (根目录) — **整合工作权威计划**: 决策/phm_v2 契约/采集架构/分阶段步骤/待办。
- `ACQUISITION_CONTRACT.md` (根目录) — **采集层全貌**: 多协议 telemetry 契约 / signal维表↔采集映射 / telemetry 写入范本 / NC 空跑 profile↔regime / 稳态门控两层。新窗口理解采集层先读它。
- `PHM_claude/PROJECT_STATUS_AND_HANDOFF.md` — 算法主线最权威现状/决策/已交付代码/待办。
- `数控机床数据采集与状态监测系统/OPCUA地址对照.xlsx` — 首台 OPC UA (Siemens 840D) 节点地址 (填 signal 维表的依据)。
- `数控机床数据采集与状态监测系统/CLAUDE.md` — 采集落库系统说明 (含 PG 库结构、连接信息、运行方式)。
- `数控机床数据采集与状态监测系统/《机床健康监测系统方案》.docx` — 旧方案 + **现场布点** (振动 3 箱体+1 前轴承套, 采样 25600Hz)。
- `PHM_claude/step1-9*.py` + `outputs/step*/` — 算法可行性验证脚本与结论 (非产品)。
- `NC-Link应用开发指导手册.docx` — NC-Link 采集协议手册 (后续 NC-Link 台份前置)。
- `_integration_probe/` — 整合期临时件 (schema 设计稿 / 建表 SQL / 连通脚本)。
