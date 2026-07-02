# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

> 项目**单一入口 (精简版)**: 只读本文件即可知道"项目是什么、现在在哪一步、不能踩什么"。
> 细节一律走 `docs/INDEX.md` 路由, **不在本文展开**。更新: 2026-06-24。
> 旧版完整入口 (~5k tok 详述) 已快照存档于 `docs/archive/CLAUDE_full_2026-06-22.md`, 仅追溯用。

## 🚦 启动协议 (每个新 session 先做)
1. 本文件已自动加载 → 已知项目全貌与核心约束 (见下)。
2. **开工前先读 `docs/CURRENT_STATE.md`** (现在在哪一步 / 上次停在哪 / 已知风险), 再动手。
3. 需要定位某块知识时, 查 `docs/INDEX.md` 路由, **只取相关 1–2 篇**, 不要全量加载。
4. 严守下方沟通约定。

## 沟通约定 (必须遵守)
- **全程中文输出。**
- **先讨论再探索**: 概念/需求先厘清, 接口与协议文档由用户提供; 不自主大范围探索或直接写代码, 改动前先对齐。

## 项目简介
重型机床 (进给 / 主轴 / 液压三系统) **健康基线系统**, 回答"这台机床现在还正常吗"。
- 核心 = **异常检测** (One-Class, 只有健康数据, 故障样本稀缺); 趋势附带; **不做** RUL, 不以故障定位为主线。
- 方法 = **自基线**: 机床与自己的过去比, 大修/拆装后按 epoch reset (跨 reset 不可比)。
- 当前主任务 = 把"现场采集系统"与"健康算法核"**整合**成一套产品。

## 技术栈
- 算法核: **Python + numpy** (纯 SVD / pinv, 无 sklearn 依赖, 模型可序列化 <5KB)。
- 数据契约: **PostgreSQL `vibration_db` 的 `phm_v2` schema** (维表 + 长表)。
- 采集: **C#** (NI-DAQmx 高频振动) + **Node** (OPC UA) + **Python** (NC-Link); 首台走 OPC UA。
- 前端: **Flask + WebSocket + 原生 JS** (无 CDN), 响应式 **v2 master-detail 看板** (机群→机床详情五标签; v1 五页平级已废弃 2026-06-29)。

## 当前阶段 (详见 `docs/CURRENT_STATE.md`)
- 算法核已验证可用 (回归锚点 + 自检全 PASS); phm_v2 契约已建并跑通; **评分回写闭环 Phase 1 已端到端验收 (真实数据)**。
- 正推进: 采集层接入 (首台 OPC UA) + 看板去 mock。

## 核心约束 (来自验证, 勿踩)
- **算法路线已锁**: 成熟期必须 PCA+T²+SPE, **SPE 不可省** (关系型异常 = 各通道边际正常但耦合变了, 是相对单变量阈值的唯一差异化价值; 单变量/对角 AUC≈0.5, 带 SPE≈1.0)。
- **温度分两类角色**: 混淆温 (环境/电机) 回归剔除; 耦合温 (轴承/油温) 进特征向量。作用相反, 别混 (落 `signal.temp_role`)。
- **工况分层**: 同工况才能比, 跨工况污染基线 (UCI 实测 FAR 可达 93%)。液压单基线 / 主轴 rpm档 (热态=协变量不分层) / 进给 轴×方向×速度档。
- **只取稳态窗**: 现场振动高度非平稳 (RMS 0.5g→25g 含瞬态), 原始整段不能直接当健康池。
- **跨 reset 不可比**: 综合健康分只在一个 epoch 内有效; 维护好坏看绝对裸指标台阶 + 维护后稳定性。
- **多协议不假设统一通道集**: 每台机床用自己的 `signal` 维表定义信号; 加协议 = 瘦采集器写 telemetry + signal 登记几行。
- **振动能力来自 NI-DAQmx 高频采集** (C#), 不是 NC-Link (后者只有寄存器轮询、无波形)。

## 子目录角色
- `PHM_claude/` — **算法与产品主线** (产品码在 `phm_pipeline/`; `step*.py` 是验证脚本, **非产品**)。
- `数控机床数据采集与状态监测系统/` — C#/Node 采集落库系统, **自带 AGENTS.md** (首台 OPC UA 事实来源)。
- `CNCDataGet/` — 现场验证的 NC-Link 轮询采集器 (后续 NC-Link 台份)。
- `_integration_probe/` — 整合期临时件 (建表 SQL / 连通脚本), 非产品。

## 开发命令 (在 `PHM_claude/` 下运行)
```bash
python -m phm_pipeline.regression_anchor   # 验证算法核复现 step7-9 数值 (改算法核后必跑)
python -m phm_pipeline.run_selfcheck       # 端到端自检 (回放 UCI 液压)
python -m phm_pipeline.smoke_test          # 模块组合冒烟
python -m phm_pipeline.server.dashboard --port 8080   # 中心只读看板
```
没有 lint/CI; "测试" = 上面自检脚本。**改算法核优先跑 `regression_anchor`**。

## 文档路由 (进入任何任务前先看 INDEX)
- **全项目知识路由器 → `docs/INDEX.md`** (告诉你该读哪一份, 不要全量加载)
- 现状 / 下一步 → `docs/CURRENT_STATE.md`
- 整合计划 (权威, A–E 阶段) → `INTEGRATION_PLAN.md`
- 采集层全貌 (多协议契约 / signal映射 / NC空跑↔regime) → `ACQUISITION_CONTRACT.md`
- 算法核现状 / 已交付代码 → `PHM_claude/PROJECT_STATUS_AND_HANDOFF.md`
- 历史 / 验证期方案 / 旧设计 → `docs/archive/`
