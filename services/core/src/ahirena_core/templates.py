"""Kullanıcı sohbet şablonları.

Parametreler {{ad}} biçimindedir. Sürüm geçmişi tutulur; otomatik model çağrısı yok.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from .db import Database, utcnow

_PARAM = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]{0,39})\s*\}\}")


class TemplateError(ValueError):
    pass


def extract_params(body: str) -> list[str]:
    return list(dict.fromkeys(_PARAM.findall(body or "")))


def render(body: str, params: dict[str, Any] | None = None) -> dict:
    values = {str(k): "" if v is None else str(v) for k, v in (params or {}).items()}
    needed = extract_params(body)
    missing = [p for p in needed if not (values.get(p) or "").strip()]
    if missing:
        raise TemplateError("Eksik parametre: " + ", ".join(missing))

    def repl(m: re.Match[str]) -> str:
        return values.get(m.group(1), "")

    text = _PARAM.sub(repl, body)
    return {"text": text, "params": needed}


def list_templates(db: Database) -> list[dict]:
    rows = db.query("SELECT * FROM prompt_templates ORDER BY updated_at DESC")
    return [_row(r) for r in rows]


def get_template(db: Database, template_id: str) -> dict:
    row = db.query_one("SELECT * FROM prompt_templates WHERE id = ?", (template_id,))
    if row is None:
        raise TemplateError("Şablon yok.")
    return _row(row)


def create_template(db: Database, name: str, body: str) -> dict:
    name = (name or "").strip()
    body = (body or "").strip()
    if not name or len(name) > 120:
        raise TemplateError("Ad 1–120 karakter olmalı.")
    if not body or len(body) > 20_000:
        raise TemplateError("İçerik 1–20000 karakter olmalı.")
    now = utcnow()
    tid = uuid.uuid4().hex
    with db.transaction() as c:
        c.execute(
            """INSERT INTO prompt_templates (id, name, body, version, created_at, updated_at)
               VALUES (?, ?, ?, 1, ?, ?)""",
            (tid, name, body, now, now),
        )
    return get_template(db, tid)


def update_template(db: Database, template_id: str, name: str, body: str) -> dict:
    current = get_template(db, template_id)
    name = (name or "").strip()
    body = (body or "").strip()
    if not name or len(name) > 120:
        raise TemplateError("Ad 1–120 karakter olmalı.")
    if not body or len(body) > 20_000:
        raise TemplateError("İçerik 1–20000 karakter olmalı.")
    if name == current["name"] and body == current["body"]:
        return current
    now = utcnow()
    next_ver = int(current["version"]) + 1
    with db.transaction() as c:
        c.execute(
            """INSERT INTO prompt_template_versions (template_id, version, name, body, archived_at)
               VALUES (?, ?, ?, ?, ?)""",
            (template_id, current["version"], current["name"], current["body"], now),
        )
        c.execute(
            """UPDATE prompt_templates SET name = ?, body = ?, version = ?, updated_at = ? WHERE id = ?""",
            (name, body, next_ver, now, template_id),
        )
    return get_template(db, template_id)


def delete_template(db: Database, template_id: str) -> dict:
    get_template(db, template_id)
    with db.transaction() as c:
        c.execute("DELETE FROM prompt_template_versions WHERE template_id = ?", (template_id,))
        c.execute("DELETE FROM prompt_templates WHERE id = ?", (template_id,))
    return {"removed": template_id}


def list_versions(db: Database, template_id: str) -> dict:
    current = get_template(db, template_id)
    rows = db.query(
        "SELECT * FROM prompt_template_versions WHERE template_id = ? ORDER BY version DESC",
        (template_id,),
    )
    versions = [
        {
            "version": current["version"],
            "name": current["name"],
            "body": current["body"],
            "active": True,
            "archived_at": None,
            "params": current["params"],
        }
    ]
    for r in rows:
        versions.append(
            {
                "version": r["version"],
                "name": r["name"],
                "body": r["body"],
                "active": False,
                "archived_at": r["archived_at"],
                "params": extract_params(r["body"]),
            }
        )
    return {"template_id": template_id, "versions": versions}


def restore_version(db: Database, template_id: str, version: int) -> dict:
    current = get_template(db, template_id)
    if int(version) == int(current["version"]):
        return current
    row = db.query_one(
        "SELECT * FROM prompt_template_versions WHERE template_id = ? AND version = ?",
        (template_id, version),
    )
    if row is None:
        raise TemplateError("Şablon sürümü yok.")
    return update_template(db, template_id, row["name"], row["body"])


def render_template(db: Database, template_id: str, params: dict[str, Any] | None = None) -> dict:
    item = get_template(db, template_id)
    out = render(item["body"], params)
    return {**out, "template_id": template_id, "version": item["version"], "name": item["name"]}


def _row(row) -> dict:
    body = row["body"]
    return {
        "id": row["id"],
        "name": row["name"],
        "body": body,
        "version": row["version"],
        "params": extract_params(body),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
