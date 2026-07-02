# 中心健康看板 (center-dashboard)

> 中心侧**只读富前端 (v2 · 方案B master-detail)**: `server/dashboard.py` + `server/static/dashboard_v2/` (纯原生无 CDN)。
> 读 phm_v2 + health_result 渲染; 健康数值评分侧算好, 看板纯读。更新: 2026-07-02。
> 运行: `python -m phm_pipeline.server.dashboard --port 8080` → 根 `/` 默认进 v2。
> **v1 (旧五页平级 `static/dashboard/`) 已废弃 (2026-06-29)**: 前端架构确定为 v2; v1 仅 `/v1/` 保留作设计参照, 勿再扩展。

## 信息架构 (方案B master-detail)
**机群列表** (汇总 + 严重度排序 + 告警原因列) → **机床详情标签** (下) → 概览卡**可点下钻**诊断 (系统上下文随标签保持) + **大屏分诊** + **设置建档** (见下) + **⌘K 命令面板**。
响应式四档断点: 手机 <600 (底部 tab) / 平板 (窄侧栏) / 桌面 / 大屏 >1600 (领导展示放大)。
设计系统: 深色令牌 (表面明度阶梯 / 语义状态三重编码 色+图标+文字 / 4px 间距 / 按钮·卡片变体)。

## 机床详情五标签
1. **概览** — 健康灯 + 建立期 x/N + 健康环形仪表/sparkline; 概览卡可点下钻诊断。
2. **诊断** — 每通道 T²(蓝)+SPE(黄高亮) 贡献双条 (锚 UCL 绝对标尺 + UCL 虚线: 正常条天然短、越限通道越线=驱动通道) + 原始波形查看。*(读 health_result 真实 t2/spe/contributions, 见 [[score-runner]])*
3. **趋势** — SVG 折线 + 阈值参考线/日期轴。*(待续: 复用线B ECharts 做密集趋势)*
4. **维护** — epoch·reset (占位)。
5. **运行** — 采集启停按钮随采集态变。

## 权限 (按能力, 非藏页)
读全开放; 写门控 = 置灰🔒 + 上报 (修正旧 v1 "只读诊断被藏、reset 对操作工敞开"的反向边界)。现场写操作接 PIN — 待接。

## 设置建档 (顶层目的地; 整合线B采集)
> 顶部有**机床快捷切换条** (各 tab 共用, `setEngMachine`): 切换即作用于当前 tab, 无需回机床管理。
- **信号映射**: `phm_v2.signal` 在线编辑器 — 逐条增/改/删 + 下拉枚举(协议/系统/类型/温度角色) + **从其他机床克隆**(默认清空地址, 应对各台 NodeId 不同) + JSON 导入导出。probe 实测确认地址仍占位(需采集器)。signal 表是采集器(解析 signal_id/地址)与算法(角色)共用的权威登记。
- **采集配置**: NI 采样率·通道·灵敏度·特征窗·事件阈值 + OPC UA endpoint·profile·轮询 + NC-Link host/port/sn + `edge{mode,gatewayId,baseUrl}` → 读写 `phm_v2.acq_config` (见 `phm_v2_acq_config.sql`)。`edge.baseUrl` 用于“打开采集工作台”, 跳到该机床 WebDashboard 边缘网关。
- **采集控制**: **统一启停**(全部启动/停止 = 一次写同置 `control.ni_run`+`control.opcua_run`, 消除人工时间差利于跨源对齐) + OPC UA·NI 单独开关 + 心跳徽标 + **波形查看/抓取**(通道下拉默认高频通道, 查看走 waveform 真实优先, 抓取写 `control.capture_signal`)。WebDashboard Node 与 C# collector 读写同一 `phm_v2.acq_config.data.control`, 中心看板不另建控制源。
- **同步·状态**: 边缘在线·store-and-forward → [[ADR-007]]。
- **机床管理**: 列出/新增/**删除**机床 (删除 = 事务全清该机床 signal/acq_config/health_result/telemetry/vib_raw_blocks + machine, 二次确认; 多机床接入 = machine 行 + 各自 signal 维表 + 各自 acq_config + 各自边缘网关)。

## API
- 读: `/api/fleet`(机群+总览聚合, boot 用) `/api/machines` `/api/overview` `/api/machine/<id>/{signals,trend,diagnose}`
- 机床: `POST /api/machines`(新增) · `DELETE /api/machines/<id>`(全清删除)
- 信号映射编辑: `POST /signals`(增/upsert) · `PUT|DELETE /signals/<sid>` · `POST /signals/{clone,import}` · `GET /signals/export`
- 采集控制: `POST /control` body `{target: ni|opcua|all, action: start|stop|capture, signal?}`
- 数控HMI投影: `/api/status/<id>`
- 边缘同步入口 (契约占位): `/api/sync`
- 采集面: `/api/machine/<id>/{acq-config(GET/PUT),control(POST),collector-status,waveform,alarms}`

## 真/mock 状态 (2026-06-30 收口: 出错不静默, mock 仅 demo)
- **两模式分明**: 生产 (连库) vs **demo** (`--no-db`/`--demo`)。**mock 仅 demo 模式可达**; 生产模式绝不端假数据。返回字段带 `source` = `real`/`empty`(无数据)/`mock`(仅 demo)。
- **生产模式三态**: 有数据→`real`; 某系统暂无 health_result 行→`empty` ("建立期/无数据", **非假绿灯**); **DB 故障→`DBError`→HTTP 503 `{degraded:true}`**, 前端 `#conn` 转红 + `#sysbar` 降级横幅 (不渲染编造健康)。
- overview/trend/diagnose 读真实 health_result; **waveform** 真实优先读 `vib_raw_blocks` (float32 块解码 + 贡献名 `<code>_<feature>` 最长前缀→signal_id), 生产无块→`empty` (不再合成假波形, 阶段B 写块后转真值)。
- 连接经 `ThreadedConnectionPool`; overview 单条 `DISTINCT ON` 查询 (消除 N+1)。口令走 `db_config.default_db()` 环境变量。
- 采集器启停·心跳: 生产模式读真实 `phm_v2.acq_config.data.control`; C# collector 已回写 `ni_state`/`ni_message`/`ni_heartbeat`/`ni_rows`/`ni_sps`/`session`/`capture_done`, Node OPC UA 已按 `control.opcua_run` reconcile。probe/告警历史未接→空 (不编造); OPC UA 标量入 telemetry 与边缘离线同步仍属后续。

## 待办 (优先级与横向比较见 `docs/CURRENT_STATE.md` 表)
- **写接口鉴权 + CORS 收紧 (P0 安全, 桌面)**: 当前权限**仅前端置灰**(`document.body.dataset.role`), 服务端写接口/`DELETE /api/machines` 无鉴权、`CORS(app)` 全开 → 多机内网部署前必做 (session/token + 写端点服务端角色校验)。
- **前端详情懒加载 (P1 桌面)**: `app.js` `loadAll` 现 boot 即为每台每系统预取 signals/acq/trend/diagnose (首屏 ~N×10 请求) → 改点开机床(`openMachine`)才拉, 首屏只 `/api/fleet` (1 请求)。后端 overview N+1 已消除, 这是前端那半。
- 生产部署: `pip install` `waitress`(默认 WSGI)/`psycopg2-binary`; `/healthz` 探针; 日志 env `PHM_LOG_LEVEL`。

## 数据来源 / 相关
- 健康值写入方 → `docs/modules/score-runner.md`
- 数据契约 → `docs/architecture/data-contract.md`
- 边缘侧 NC-Link 控制台 (≈edge) → `PHM_claude/phm_pipeline/server/README.md`
- 部署形态 (边缘/中心分离) → [[ADR-007]]
- 整合计划 D 阶段 → `INTEGRATION_PLAN.md §D`
