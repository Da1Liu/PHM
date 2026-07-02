# 机床健康基线控制台 (NC-Link 采集 + 健康评分一体化)

把 **NC-Link 寄存器轮询采集** 接到 `phm_pipeline` 的健康基线算法上, 提供一个浏览器控制台:
**连接 → 通道映射(可 probe 验证) → 按窗口采集 → 入库 → 生命周期健康评分 → 趋势/告警/贡献看板**。

## 快速开始

```bash
cd PHM_claude
pip install -r phm_pipeline/server/requirements.txt

# 无硬件先体验整套界面 (合成数据, 可用 drift 滑块注入退化)
python -m phm_pipeline.server.app --mock

# 接真实 NC-Link API Server
python -m phm_pipeline.server.app --port 9000
```
浏览器打开 `http://127.0.0.1:9000`。Windows 可双击 `start_console.bat`。

> 前置: 真实模式需先按《NC-Link应用开发指导手册》启动 **EMQ(MQTT:1883)** 与 **API Server(java -jar, HTTP)**，
> 机床 `nclink.cfg` 指向 MQTT。控制台只跟 **API Server** 的 HTTP 接口打交道。

## 使用流程

1. **连接**: 填 API Server 地址/端口(现场常用 19001)/设备 SN，点"连接/测试"(拉 model 验证连通)。
2. **通道映射**: 点"加载 model.json 候选"列出设备数据项 →
   - `+` 加入映射；给每个通道设 **PHM名 / 角色 / 特征(reducer) / index / 公式(可选)**。
   - 角色: `channel`(进特征向量) · `confounder_temp`(混淆温度,存档) · `condition`(工况标签)。
   - **重要**: model.json 接口随驱动版本未必全有效 → 勾选后点 **"probe 选中"** 实测能否取到值，再"保存映射"。
3. **采集**: 设采集周期/窗口点数/工况标签，点"开始采集"。一个窗口 = 轮询 N 次组成各通道序列。
4. **看板**: 实时健康度/阶段/score/T²/SPE、健康度趋势曲线、告警(双层去抖)、成熟期贡献归因、采集历史。

## 关键设计 (与已验证算法一致)

- **只走寄存器轮询** (`get_value`): 当前 NC-Link 版本无波形订阅，故只能算标量遥测类特征
  (电机负载电流/位置/速度的 mean/std/rms 等)，**高频振动 RMS/峭度需 kHz 波形, 拿不到**。
- **生命周期三阶段**: n<30 工程先验(CUSUM) → 30–100 分位评分 → 成熟期 **PCA+T²+SPE**，
  50–200 混合过渡。成熟期 `score>1` 的样本**不准入基线**(防故障污染)。
- **健康度** `health=exp(-3·max(T2/UCL_T2, SPE/UCL_SPE))`；**双层告警** L1物理限 ∥ L2模型，
  EWMA + K连续去抖。以上全部复用 step1–9 验证过的核 (见 `regression_anchor.py`)。

## 数据落地 (SQLite, 单文件)

`outputs/console/health.db`：`collections`(窗口元信息+原始序列压缩) · `features` · `health` ·
`models`(基线模型序列化) · `config`(连接/映射)。重启后回放历史 → 生命周期状态连续。

## 自检 (无需硬件)

```bash
python -m phm_pipeline.server.e2e_mock_test
```
mock 走完 132 窗口/18 模拟日，断言：进成熟期、训出模型、健康段健康度高且 FAR<10%、注入退化后健康度跌且告警。

## 接真机要确认/标定的点

- **SN 与 API Server 端口**(现场)、各 PHM 通道对应的 **NC-Link 路径@index**(用 probe 落实)。
- **稳态段**: 默认取窗口 20%–90%；若热机程序节奏不同，按需调 `FeatureSpec.seg_*`。
- **物理限 L1**: `SystemConfig.physical_limits` 现为空，按电机铭牌/规格书填。
- **工况分层**: v1 单基线；要按 转速/进给档 分层时给 `condition` 通道并开 `baseline_by`。
- **混淆温度回归**: v1 引擎暂只存档不在线剔除 (整套回归在离线 `phm_pipeline` 已具备)。

## 模块

```
acquisition/nclink_client.py  NC-Link HTTP 客户端(get_value/model/probe/ping) + MockNclinkClient
acquisition/model_file.py     解析 model.json -> 候选寄存器
acquisition/channel_map.py    NC-Link {path,index} -> PHM 通道/温度/工况 + reducer/公式
acquisition/collector.py      轮询一窗 -> CollectionRecord
datasource.RealSource         把 Collector 包成 DataSource (已落地)
store/db.py                   SQLite 存储
server/engine.py              映射->SystemConfig, 串 特征/生命周期/告警/贡献
server/app.py                 Flask 服务 + 全部 API + WebSocket
server/static/index.html      单页控制台 (无外部 CDN 依赖)
server/e2e_mock_test.py       端到端自检
```
