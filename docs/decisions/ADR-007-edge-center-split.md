# ADR-007 边缘 store-and-forward + 中心只读富前端

状态: 已采纳

## Decision
- **边缘 (每机床)**: 事件触发采集 → 特征 → PHM 评分/生命周期 → 本地 SQLite 缓冲 → 驱动数控 HMI 简略健康界面 → 联网后 push 未同步样本到中心 `/api/sync`。
- **中心 (内网服务器)**: 汇总各机床 phm_v2 + health_result → **只读**服务响应式富前端 (平板/手机 iOS安卓/办公) + 综合大屏 (领导展示)。
- 代码现在就按"引擎/前端可分离"写。

## Reason
- 数据是**事件性**的 (交班/热机后才一个样本, 非连续), 且要扛**断网** → store-and-forward。
- 数控 HMI 简略界面需本地可达、断网免疫。

## Consequence
- `server/app.py` (NC-Link 控制台) ≈ 边缘侧; `server/dashboard.py` (只读看板) = 中心侧。
- 近期同一进程; 将来引擎下沉边缘、前端留中心, **零重写**。
- 建立期 x/N 以"月"计 (事件节奏); 评分侧算好显示字段, 中心看板纯读 (见 `docs/modules/score-runner.md`)。
