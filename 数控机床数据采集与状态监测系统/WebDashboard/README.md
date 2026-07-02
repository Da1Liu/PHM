# WebDashboard —— 只读趋势看板 (Phase 1)

数控机床采集落库模块的 **Web 只读趋势看板**。不改动现有 WinForms 采集程序，直连同一个 PostgreSQL（`vibration_db`），展示主轴/进给各轴/坐标/振动趋势。**无报警、无写入、无实时推送**（按需求范围）。

> 背景与完整方案见 `~/.claude/plans/web-fluffy-yao.md`。
> NI-DAQmx 采集必须留在硬件所在 Windows 主机；OPC UA 及所有读路径可自由 Web 化。本看板是读路径。

## 目录结构
```
WebDashboard/
  api/                  # Node + Express + pg 只读 API
    src/server.js       # 路由 + 静态托管
    src/repository.js   # SQL 查询 + 表名白名单 + 数据库侧降采样
    src/db.js           # pg 连接池（读 .env）
    .env.example        # 连接串模板
  web/                  # 静态前端（ECharts via CDN，无需构建）
    index.html app.js styles.css
```

## 运行
```powershell
cd WebDashboard/api
npm install
copy .env.example .env   # 然后按实际环境改 .env
npm start                # 默认 http://localhost:4000
```
浏览器打开 `http://localhost:4000` 即看板。

### 配置 `.env`（重要）
连接串**不再硬编码**，全部走 `.env`：
```
PGHOST=localhost
PGPORT=5432
PGDATABASE=vibration_db
PGUSER=postgres
PGPASSWORD=<本机 PostgreSQL 实际密码>
PORT=4000
MAX_POINTS=1000
```
> 注意：桌面程序 `PostgreSQL.cs` 里写死的是 `postgres / 123456`。若本机 Postgres 密码不同，必须在 `.env` 填实际密码，否则 `/api/health` 返回 `password 认证失败`。

## API
| 方法 & 路径 | 说明 |
|---|---|
| `GET /api/health` | 健康检查（探测 DB 连接） |
| `GET /api/tables` | 列出可用表（振动 `*_main` / `*_bool` / `*_other` / 固定 OPCUA 表） |
| `GET /api/spindle/trend?from&to&maxPoints` | 主轴电流/温度/转速（读 `_OPCUA_2`） |
| `GET /api/axes/trend?metric&axes&from&to&maxPoints` | 各轴电流/温度/速度（读 `_OPCUA_3`）；`metric=current\|temperature\|speed`，`axes=x1,x2,...` |
| `GET /api/coordinates?from&to&maxPoints` | 机械/绝对坐标（读 `_OPCUA_new`） |
| `GET /api/vibration/range?table=` | 指定振动表的 id 首尾游标 |
| `GET /api/vibration?table&channels&start&end&maxPoints` | 振动波形（按 id 区间 + 降采样） |

`from`/`to` 为 ISO 时间串；`maxPoints` 为数据库侧降采样目标点数（10–5000）。

## 设计要点 / 与桌面端的对应
- **表名白名单**：动态振动表名（`tb_YYYY_..._main`）走 `information_schema` 存在性校验，固定表硬编码，杜绝 SQL 注入。
- **降采样**：`repository.js` 的 `buildDownsample` 用 `row_number() % step` 在 SQL 侧等距抽稀，等价于桌面端 `Form2.DownsampleData`，但避免全量传输。
- **字段语义**：图例中文名对应 `WindowsFormsApp1/数据库对照.txt` 与 `GlobalVariables.cs`。
- **表结构来源**：`_OPCUA_2/_OPCUA_3/_OPCUA_new` 列定义对应 `PostgreSQL.cs` 的 `CreateOPCUA2/CreateOPCUA3/CreateMachineCoordinatesTable`。

## 已验证 / 待验证
- ✅ 服务启动、静态托管、路由与参数校验、DB 异常优雅返回（500 + 明确错误）。
- ⏳ 真实数据渲染：需 `.env` 填入正确 Postgres 密码、且 `vibration_db` 中已有桌面程序采集的数据后，对照桌面端同时段曲线核对趋势形状。
