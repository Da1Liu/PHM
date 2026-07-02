# 机床健康基线项目 — 进度与衔接文档

> 用途: 新开对话时快速理解项目现状、已定决策、已交付代码、待办事项, 实现工作衔接.
> 更新日期: 2026-06-16 (新增 NC-Link 采集控制台)
> 工作目录: `D:/Proj/PHM_realtest`; 代码与数据在 `PHM_claude/` 子目录.
> ⚠️ 本文是**算法核**现状权威; **项目级最新现状/下一步**见 `docs/CURRENT_STATE.md`, 整合计划见 `INTEGRATION_PLAN.md`。本文"液压=第一个落地系统"指**算法验证顺序**(UCI 液压); **整合阶段首台真机落地主系统已定为主轴**(该机液压仅 bool 压力监测, 见 INTEGRATION_PLAN A2)。

---

## 1. 项目是什么

重型机床健康基线系统 (进给 / 主轴 / 液压三系统), **第一阶段只做异常检测** (不做故障定位).
每次热机后空运行产出一个健康度 [0,1] + 趋势 + 告警. 本质是 One-Class 问题 (只有健康数据, 故障数据稀缺).

**部署上下文 (关键, 决定方案形态)**:
- 即将在真实机床采集数据. 系统既上新机, 也上**存量设备**.
- **无同型号健康参考机**. 存量策略: 先验证算法能否揭示存量机退化现象 (设备一直加工, 退化客观存在),
  验证通过后靠**人工大修 reset 健康状态**再正式起基线. 用户能确认当前精度是否达标 (外部锚点).
- 数据采集通道协议**用户后续提供文档**, 当前解耦留桩.

---

## 2. 讨论中已拍板的关键决策

| 议题 | 结论 | 依据 |
|---|---|---|
| 成熟期算法 | **PCA + T2 + SPE**, `score=max(T2/UCL_T2, SPE/UCL_SPE)` | step7-9 验证; SPE 不可省 (抓"边际正常但关系异常") |
| 温度处理 | 混淆温度(环境/电机)回归剔除; 耦合温度(轴承/油温)进向量 | step5 vs step9 两类证据 |
| 工况分层 | = 诊断分辨率旋钮, 取"满足诊断需求的最粗分层". 非外部强制 | 用户纠正: 健康数据不稀缺, 分层粒度自定 |
| 液压诊断目标 | 仅系统效率退化, **单基线**. 第一个落地系统 | 最接近已验证场景 |
| 主轴诊断目标 | 前后轴承都要 (有指导维护意义); 但前后振动进**同一向量**靠贡献分解归因, 不拆独立基线 | 保留跨轴承耦合关系 |
| 进给诊断目标 | 愿为磨损做精细速度分层 | — |
| 进给反向间隙 | 第一版**不接数控跟随误差**(权限问题) → 反向间隙只能弱检测/暂不承诺; 导轨磨损仍可做 | 反向间隙是换向瞬态现象, 需跟随误差/换向段 |
| 冷启动模拟 | 磨合污染检测 v1 **只留接口不实现** (存量优先, 靠大修reset) | 用户同意 defer |
| 运行时 | 先 Python/numpy 桌面, 边缘移植后置 | — |
| 采集通道 | 解耦留桩 (RealSource), 等用户协议文档 | — |

**重要提醒**: 原始 `cnc_health_baseline_technical_plan.md` (5月, 现归档于 `docs/archive/`) 的部分设定已被验证推翻
(它写的是对角 T2、温度一律剔除). 以本文档和 step7-9 结果为准, 勿照搬旧 .md.

---

## 3. 已验证的结论 (step1-9, 证据基础)

- **多传感器联合基线可行**; 成熟期 PCA+T2+SPE 最优, 正则化协方差次之, 裸 full-cov+pinv 病态排除
  (cond# 1.1e8), 对角/单变量不足以覆盖耦合异常.
- **关系异常测试 (step9) 是杀手锏**: 单变量/对角 AUC≈0.5 形同失明, 只有带 SPE 的模型能看到
  "各通道边际都正常、但耦合关系变了". 这是本方案相对传统阈值的唯一差异化价值.
- **温度** (step5): 混淆温度回归剔除使单通道检测预警提前量 194→407min.
- 证据局限: step1-9 只覆盖轴承振动(FEMTO)和液压多传感器(UCI), **不含进给轴数据**.
  进给反向间隙的判断是物理推理, 未经数据验证 (若要坐实需 PHM 2021 滚珠丝杠数据集).

---

## 4. 已交付的 v1 代码

包: `PHM_claude/phm_pipeline/` (纯 numpy, SVD, pinv, 沿用 step1-9 风格)

```
datasource.py   采集解耦点: CollectionRecord 契约 + FileSource(回放UCI)/MockSource/RealSource(桩)
segment.py      稳态窗口(复用step7) + 匀速段截断(电流跃变法, 进给用)
features.py     逐通道reducer→特征向量 (FeatureSpec 配置驱动) + 派生特征(q_over_p)
covariate.py    TempResidualizer: 混淆温度回归剔除(复用step5)
model.py        BaselineModel(PCA+T2+SPE, 样本外UCL标定, 序列化) + RegularizedCovModel(兜底)
score.py        health映射 + T2/SPE 特征贡献分解(新)
alarm.py        AlarmState: 双层(物理限∥模型) + EWMA + K连续去抖
lifecycle.py    LifecycleManager: 三阶段切换 + 50-200混合 + 基线准入门控(新)
selfcheck.py    FAR / 基线稳定性 / 阶段切换连续性 / 数据质检
config.py       SystemConfig + hydraulic_v1(); 进给/主轴占位; mature_min_n=max(100,10p)
contamination.py 稳定性加权/IsolationForest 留接口(不实现)
regression_anchor.py  共享核 vs step7-9 数值对照
run_selfcheck.py      端到端: 回放UCI液压为逐日流, 跑通整条生命周期
smoke_test.py         MockSource 单条记录跑通每层
```

### 运行方式 (在 `PHM_claude/` 目录下)
```
python -m phm_pipeline.regression_anchor   # 验证共享核等价于 step7-9
python -m phm_pipeline.run_selfcheck       # 端到端自检, 输出 outputs/selfcheck/
python -m phm_pipeline.smoke_test          # 模块组合冒烟测试
```

### 4b. NC-Link 采集控制台 (2026-06-16 新增)

把现场 NC-Link 协议接到上面的算法核, 形成"连接→映射→采集→入库→评分→看板"一体化前端.
依据: `NC-Link应用开发指导手册.docx` + 现场已验证的 `CNCDataGet/`(寄存器轮询 + model.json).

**已确认事实**: 当前 NC-Link 版本**只有寄存器轮询(get_value), 无波形订阅** → 只能算标量遥测
类特征(电机负载电流/位置/速度 mean/std/rms…), 高频振动 RMS/峭度拿不到; model.json 接口
**随驱动版本未必全有效**, 故映射必须 **probe 实测** 后再用.

```
phm_pipeline/acquisition/
  nclink_client.py  NC-Link HTTP 客户端 + MockNclinkClient(离线演示)
  model_file.py     解析 model.json -> 候选寄存器(本机 41 项: X/Y/Z/C 轴电机电流/位置/速度 + 寄存器表)
  channel_map.py    NC-Link {path,index} -> PHM 通道/温度/工况 + reducer/公式
  collector.py      轮询一个采集窗口 -> CollectionRecord
datasource.RealSource  已落地(包 Collector); 阻塞项解除
phm_pipeline/store/db.py   SQLite 单文件存储(采集窗口/特征/健康度/模型/配置), 重启回放恢复
phm_pipeline/server/
  engine.py         映射->SystemConfig, 串 特征/生命周期/告警/贡献
  app.py            Flask 服务 + 全部 API + WebSocket 实时推送
  static/index.html 单页控制台(无 CDN 依赖): 连接/映射probe/采集/健康看板趋势告警贡献
  e2e_mock_test.py  端到端自检(无需硬件)
  README.md / requirements.txt / start_console.bat
```
运行: `pip install -r phm_pipeline/server/requirements.txt` 后
`python -m phm_pipeline.server.app --mock`(演示) 或 `--port 9000`(真机), 浏览器开 `http://127.0.0.1:9000`.

---

## 5. 验证结果 (全部通过)

**回归锚点**: 共享核**精确复现** step7 (全特征 AUC=1.000/Spearman=0.924/FAR=1.47%) 和
step8 (剔除强单变量后 PCA+T2+SPE=1.000 / 对角=0.747 / max-z=0.681). 重构未破坏算法.

**端到端自检** (回放UCI液压, 健康→pump1→pump2): 全 PASS
- 去抖告警 FAR = 0% (原始单点超限 ~7% 由 EWMA+K=5 去抖消除)
- 阶段切换 EWMA趋势无跳变 (边界跳变 0.075 vs 波动p95 0.026)
- score 随 pump 单调 (Spearman 0.943); health pump0/2 = 0.83/0.10
- pump=2 贡献分解指向 q_over_p/fs1/se (压力/流量/效率), 正确
- 数据质检正确标记 UCI 缺失班次时长
- 曲线: `outputs/selfcheck/selfcheck_curves.png`

### 自检在桌面上排掉的三个上真机会踩的雷 (这是自检的核心价值)
1. **工况未分层污染基线**: UCI "健康"池混 16 个 valve×accumulator 工况且按扫描排序 →
   训练/打分落不同工况 → FAR 93%. 印证"工况分层必须严格". (修正: 同工况内打乱消除排序假象)
2. **小样本 UCL 偏乐观**: 14 特征需 n≥10p=140 (加 mature_min_n 门控), UCL 必须用留出近期健康样本
   做样本外标定; 部署 FAR 以去抖告警率为准.
3. **故障污染基线**: 朴素地把每条样本并入基线 → 基线随故障漂移、健康度虚假回升.
   (修正: 成熟期 score>1 的样本不准入基线; 完整污染检测仍留接口)

---

## 6. 待办 / 下次从哪接

**已完成 (原阻塞项)**:
- [x] **真实采集**: NC-Link 寄存器轮询已接入 `RealSource` + 采集控制台 (见 4b). 端到端自检通过.

**接真机前要现场确认/标定 (需用户)**:
- [ ] 设备 SN、API Server 端口; 各 PHM 通道对应的 NC-Link 路径@index (控制台里 probe 落实).
- [ ] 物理限 L1 (`SystemConfig.physical_limits` 现为空, 按电机铭牌/规格书填).
- [ ] 稳态段 seg_start/end 是否匹配现场热机程序节奏.

**可并行推进 (不阻塞)**:
- [ ] 进给系统特征集与分层落地 (config 里现为占位): 轴×方向×速度档, 导轨磨损特征.
- [ ] 主轴系统特征集与分层落地: rpm档×热态, 前后轴承振动同向量.
- [ ] (可选) 拉 PHM 2021 滚珠丝杠数据集, 验证进给反向间隙/磨损是否可检测.
- [ ] 模型参数序列化下发的边缘侧推理最小实现 (BaselineModel.to_dict 已就绪, <5KB).

**已明确不在 v1 范围**: 磨合污染检测、进给跟随误差/反向间隙、边缘嵌入式移植.

---

## 7. 相关文件索引
- 本文档: `PHM_claude/PROJECT_STATUS_AND_HANDOFF.md`
- 计划文件: `C:/Users/Administrator/.claude/plans/peaceful-whistling-horizon.md`
- 验证脚本与结论: `PHM_claude/step1-9*.py`, `outputs/step*/`,
  `docs/archive/validation-plans/multisensor_covariance_baseline_validation_plan.md` (含已执行阶段结论 §13)
- 旧技术方案(部分已过时, 已归档): `docs/archive/cnc_health_baseline_technical_plan.md`,
  `docs/archive/cnc_multisensor_health_baseline_implementation_plan.md`
