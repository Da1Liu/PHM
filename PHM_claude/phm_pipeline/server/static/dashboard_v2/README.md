# dashboard_v2 — 中心看板重构原型 (方案B master-detail)

产品设计评审驱动的**独立**前端原型, 与生产看板 `../dashboard/` 并存、互不影响。
复用同一套后端 `/api/...` (见 `../../dashboard.py`)。

## 怎么看
- **接真实接口 (推荐)**: `cd PHM_claude && python -m phm_pipeline.server.dashboard --port 8080`,
  浏览器开 `http://127.0.0.1:8080/v2/` (尾斜杠不能省 —— 相对引用 styles.css/app.js 靠它解析)。
  - 顶栏显示 **"在线·真实接口"**; 数据来自 `/api`。`--no-db` 则后端走 mock, 适配层照常工作。
- **静态直开**: 双击 `index.html` (file://)。fetch 失败 → 自动**回退静态占位** (CNC_01..04),
  顶栏显示 **"离线·静态占位"**。设计走查无需起服务即可看全。

## 结构 (纯原生, 无构建/无外部依赖)
- `index.html` — 壳 (顶栏 + #app + ⌘K 面板)。
- `styles.css` — 设计系统令牌 (深色; 表面阶梯 / 语义状态三重编码 色+图标+文字 / 4px 间距 / 按钮·卡片变体)。
- `app.js` — SPA: 视图路由 + 渲染 + **真实接口适配层** (文件末 "真实接口适配层" 段)。

## 视图
机群列表 → 机床详情(概览 / 诊断 / 趋势 / 维护 / 运行) → 概览卡**下钻**诊断(系统上下文随标签保持);
大屏分诊; 设置·建档(机床管理 / 信号映射 / 采集配置 / 同步·状态); ⌘K 命令面板。
角色 操作工/工程师: **读全开放, 写门控**(置灰🔒 + 上报提示, 非藏页)。

## 适配层约定 (接口 ↔ 渲染解耦)
在线时把 `/api` 响应映射进与静态占位**同构**的 `DATA / SIGNALS / ACQ / STATUS / RUN`, 渲染层不感知数据来源:
- 读: machines / overview / diagnose / trend / signals / acq-config / collector-status / waveform / alarms
- 写: control(启停/抓波形) / signals CRUD·clone·import·export / acq-config save / machine 接入·删除
- mode 映射: 后端 `scoring`→`scored`; building→灯 `slate`; status_only→灯 `l1`。

## 已知小限制 (占位)
- 采集配置「保存」在线回写**当前已载入配置**(表单内编辑值的逐字段回读尚未接, 信号映射编辑则已逐字段回读)。
- 告警/同步状态在真实边缘采集器接入(阶段B)前仍是后端占位。
