"""SQL Server sorgularını uygulamaya varmadan salt okunur diye süzer.

Sunucunun kendi 'read only' etiketi kabul edilmez. Yorum, birden fazla ifade,
yazma ve yordam çağrısı reddedilir. Bu dosya bağlantı açmaz.
"""

from __future__ import annotations

import re

_START = re.compile(r"(?is)^(select|with)\b")
_FORBIDDEN = re.compile(
    r"(?is)\b(insert|update|delete|drop|alter|exec|execute|merge|grant|revoke|create|truncate|"
    r"backup|restore|dbcc|into|openrowset|opendatasource|bulk)\b|\bxp_\w+\b|\bsp_\w+\b"
)


class SqlRejected(ValueError):
    pass


def assert_readonly(sql: str) -> str:
    text = (sql or "").strip()
    if text.endswith(";"):
        text = text[:-1].strip()
    if not text:
        raise SqlRejected("Sorgu boş.")
    if ";" in text or "--" in text or "/*" in text:
        raise SqlRejected("Tek ifade olmalı; yorum ve ikinci ifade kabul edilmez.")
    if not _START.match(text):
        raise SqlRejected("Yalnızca SELECT kabul edilir.")
    if _FORBIDDEN.search(text):
        raise SqlRejected("Yazma, yordam veya dosya erişimi kabul edilmez.")
    return text


TABLES_SQL = assert_readonly(
    "SELECT TABLE_SCHEMA, TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
    "WHERE TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_SCHEMA, TABLE_NAME"
)
PROBE_SQL = assert_readonly("SELECT 1 AS ok")
