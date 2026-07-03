"""中心侧 PostgreSQL 连接参数集中点 (去硬编码口令).

中心看板 / 评分回写 / 采集落库桥共用此处的 default_db(), 口令一律从环境变量读,
源码不留明文默认值. 非 DB 路径 (dashboard --no-db / 纯算法核自检) 不调用此函数,
故无口令也能跑.

口令来源 (优先级): **环境变量** > `PHM_claude/.env` 文件兜底. 即:
  - 生产推荐: 设持久环境变量 (Windows: [Environment]::SetEnvironmentVariable(..., 'Machine')).
  - 或在 `PHM_claude/.env` 写 `PHM_PGPASSWORD=...` (该文件已 .gitignore, 不进版本库;
    模板见 `PHM_claude/.env.example`). 环境变量若已设则覆盖 .env.

环境变量/键 (仅 PHM_PGPASSWORD 无默认, 缺失即报错):
  PHM_PGHOST      默认 localhost
  PHM_PGPORT      默认 5432
  PHM_PGUSER      默认 postgres
  PHM_PGDATABASE  默认 vibration_db
  PHM_PGPASSWORD  **必填**, 未设置且 .env 也无 -> DBConfigError
"""
from __future__ import annotations

import os

from .domain.shared.ownership import DATA_OWNERSHIP

# PHM_claude/ 目录 (本包的上级), .env 与 .env.example 落在此处.
_PKG_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DOTENV_PATH = os.path.join(_PKG_PARENT, ".env")
_dotenv_loaded = False

# Ownership metadata only. default_db() still returns the current PostgreSQL connection.
DB_OWNERSHIP = DATA_OWNERSHIP


class DBConfigError(RuntimeError):
    """DB 连接参数缺失 (通常是未设置 PHM_PGPASSWORD)."""


def _load_dotenv_once() -> None:
    """把 PHM_claude/.env 中的键载入 os.environ (零依赖, 只读一次).

    环境变量优先: 仅填补 os.environ 里尚未存在的键, 不覆盖已设置的真实环境变量.
    解析容错: 跳过空行/注释(#)/无 '=' 行; 去掉值两端引号; 任何异常静默忽略 (不拖垮启动).
    """
    global _dotenv_loaded
    if _dotenv_loaded:
        return
    _dotenv_loaded = True
    if not os.path.isfile(_DOTENV_PATH):
        return
    try:
        with open(_DOTENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:   # 环境变量优先, .env 仅兜底
                    os.environ[key] = val
    except Exception:  # noqa: BLE001  .env 解析失败不应导致启动崩溃
        pass


def default_db() -> dict:
    """构造 psycopg2.connect(**kwargs) 用的连接参数 dict.

    惰性求值: 仅在确实需要连库时调用 (不在模块 import 期), 这样 --no-db / 纯算法核
    路径无需设置口令. 先尝试加载 .env 兜底, 再读环境变量; 缺 PHM_PGPASSWORD 抛
    DBConfigError, 报清晰错误而非用明文默认值.
    """
    _load_dotenv_once()
    password = os.environ.get("PHM_PGPASSWORD")
    if not password:
        raise DBConfigError(
            "未设置 PHM_PGPASSWORD; 中心看板/评分/采集桥连接 PostgreSQL 需 DB 口令。\n"
            "  方式一 (推荐, 持久环境变量, PowerShell 管理员):\n"
            "    [Environment]::SetEnvironmentVariable('PHM_PGPASSWORD','你的口令','Machine')  # 重开 shell 生效\n"
            "  方式二 (仓库内入口): 复制 PHM_claude/.env.example 为 PHM_claude/.env, 填入口令 (该文件不进 git)。\n"
            "  方式三 (临时, 仅当前窗口): $env:PHM_PGPASSWORD='你的口令'\n"
            "  仅看演示不连库: dashboard 加 --no-db。")
    return dict(
        host=os.environ.get("PHM_PGHOST", "localhost"),
        port=int(os.environ.get("PHM_PGPORT", "5432")),
        user=os.environ.get("PHM_PGUSER", "postgres"),
        password=password,
        dbname=os.environ.get("PHM_PGDATABASE", "vibration_db"),
    )


