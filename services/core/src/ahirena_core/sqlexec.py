"""SQL Server'a Windows kimliğiyle salt okunur bağlantı.

Parola config.json'a yazılmaz. Yazma sorgusu buraya gelmeden sqlguard'da düşer.
Sürücü yoksa veya sunucu tanımlı değilse uydurma satır dönülmez.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .sqlguard import PROBE_SQL, SqlRejected, assert_readonly

ROW_LIMIT = 50


@dataclass(frozen=True)
class SqlConfig:
    enabled: bool = False
    server: str = ""
    database: str = ""
    driver: str = ""

    @classmethod
    def from_dict(cls, raw: dict) -> "SqlConfig":
        known = {k: raw[k] for k in ("enabled", "server", "database", "driver") if k in raw}
        cfg = cls(**known)
        if any(k in raw for k in ("password", "pwd", "uid", "user", "username")):
            raise ValueError("Parola veya SQL kullanıcısı kaydedilmez; Windows kimliği kullanılır.")
        return cfg


def load_sql_config(data_dir: Path) -> SqlConfig:
    path = data_dir / "config.json"
    if not path.exists():
        return SqlConfig()
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    return SqlConfig.from_dict(raw.get("sql") or {})


def save_sql_config(data_dir: Path, cfg: SqlConfig) -> None:
    path = data_dir / "config.json"
    raw = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    raw["sql"] = asdict(cfg)
    path.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")


def _driver() -> str:
    try:
        import pyodbc
    except ImportError as e:
        raise SqlRejected("pyodbc kurulu değil. SQL sorgusu çalıştırılamaz.") from e
    installed = set(pyodbc.drivers())
    for name in ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server"):
        if name in installed:
            return name
    raise SqlRejected("SQL Server ODBC sürücüsü yok (17 veya 18).")


def query(cfg: SqlConfig, sql: str) -> dict:
    if not cfg.enabled or not cfg.server or not cfg.database:
        raise SqlRejected("SQL Server yapılandırılmadı. Ayarlarda sunucu ve veritabanı yazılmalı.")
    statement = assert_readonly(sql)
    driver = cfg.driver or _driver()
    try:
        import pyodbc
    except ImportError as e:
        raise SqlRejected("pyodbc kurulu değil.") from e
    conn_str = (
        f"DRIVER={{{driver}}};SERVER={cfg.server};DATABASE={cfg.database};"
        "Trusted_Connection=yes;Encrypt=yes;TrustServerCertificate=yes;"
    )
    try:
        conn = pyodbc.connect(conn_str, timeout=5, readonly=True)
    except pyodbc.Error as e:
        raise SqlRejected(f"Bağlantı kurulamadı: {e}") from e
    try:
        cur = conn.cursor()
        cur.execute(statement)
        columns = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchmany(ROW_LIMIT)
        return {
            "columns": columns,
            "rows": [[None if v is None else str(v) for v in row] for row in rows],
            "truncated": len(rows) >= ROW_LIMIT,
        }
    except pyodbc.Error as e:
        raise SqlRejected(f"Sorgu başarısız: {e}") from e
    finally:
        conn.close()


def probe(cfg: SqlConfig) -> dict:
    return query(cfg, PROBE_SQL)
