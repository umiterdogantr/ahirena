"""Doğal dilden yetenek taslağı.

Aday karantinadadır. İzin, test ve içe aktarma olmadan etkinleşmez.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from .db import Database, utcnow
from .skills import AUDITED_TOOLS, SkillError, package_hash, parse_capabilities, parse_skill_md

_SLUG = re.compile(r"[^a-z0-9-]+")


def _slug(text: str) -> str:
    base = text.lower().replace("ı", "i").replace("ş", "s").replace("ğ", "g").replace("ü", "u").replace("ö", "o").replace("ç", "c")
    base = _SLUG.sub("-", base).strip("-")[:32] or "aday"
    return base


def draft_skill(db: Database, data_dir: Path, prompt: str, tools: list[str] | None = None) -> dict:
    text = (prompt or "").strip()
    if len(text) < 8:
        raise SkillError("Açıklama en az 8 karakter olmalı.")
    chosen = list(tools or [])
    if not chosen:
        low = text.lower()
        if any(w in low for w in ("saat", "zaman", "clock")):
            chosen.append("clock.now")
        if any(w in low for w in ("dosya", "oku", "klasör", "folder", "file")):
            chosen.append("files.read")
        if any(w in low for w in ("sql", "sorgu", "tablo", "veritaban")):
            chosen.extend(["sql.query", "sql.tables"])
        if not chosen:
            chosen = ["clock.now"]
    unknown = [t for t in chosen if t not in AUDITED_TOOLS]
    if unknown:
        raise SkillError("Taslak yalnızca denetlenmiş araçlar isteyebilir: " + ", ".join(unknown))
    chosen = list(dict.fromkeys(chosen))
    name = _slug(text.split(".")[0].split(",")[0])[:40]
    description = text[:400]
    skill_md = (
        f"---\nname: {name}\ndescription: {description}\n---\n\n"
        f"{text}\n\nBu metin izin vermez ve uygulama yetkisini değiştirmez.\n"
    )
    capabilities = json.dumps(
        {"format": "ahirena-capabilities", "version": 1, "tools": chosen, "network": "none"},
        ensure_ascii=False,
        indent=2,
    )
    parse_skill_md(skill_md)
    parse_capabilities(capabilities)
    digest = package_hash(skill_md, capabilities)
    cid = uuid.uuid4().hex
    dest = data_dir / "skills" / "_candidates" / cid
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "SKILL.md").write_text(skill_md, encoding="utf-8")
    (dest / "capabilities.json").write_text(capabilities, encoding="utf-8")
    now = utcnow()
    with db.transaction() as c:
        c.execute(
            """INSERT INTO skill_candidates
               (id, name, description, tools_json, package_dir, content_hash, prompt, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'candidate', ?)""",
            (cid, name, description, json.dumps(chosen), str(dest), digest, text, now),
        )
    return {
        "id": cid,
        "name": name,
        "description": description,
        "tools": chosen,
        "package_dir": str(dest),
        "content_hash": digest,
        "status": "candidate",
        "enabled": False,
        "note": "Aday karantinada. İçe aktarıp izin vermeden çalışmaz.",
    }


def list_candidates(db: Database) -> list[dict]:
    rows = db.query("SELECT * FROM skill_candidates WHERE status = 'candidate' ORDER BY created_at DESC")
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "description": r["description"],
            "tools": json.loads(r["tools_json"]),
            "package_dir": r["package_dir"],
            "content_hash": r["content_hash"],
            "status": r["status"],
            "enabled": False,
        }
        for r in rows
    ]


def discard_candidate(db: Database, candidate_id: str) -> dict:
    import shutil

    row = db.query_one("SELECT * FROM skill_candidates WHERE id = ?", (candidate_id,))
    if row is None:
        raise SkillError("Aday yok.")
    with db.transaction() as c:
        c.execute("UPDATE skill_candidates SET status = 'discarded' WHERE id = ?", (candidate_id,))
    package = Path(row["package_dir"]) if row["package_dir"] else None
    if package and package.is_dir() and "_candidates" in package.parts:
        shutil.rmtree(package, ignore_errors=True)
    return {"discarded": candidate_id, "package_removed": bool(package and not package.exists())}


def mark_imported_by_path(db: Database, package_dir: str) -> int:
    path = str(Path(package_dir).resolve())
    with db.transaction() as c:
        cur = c.execute(
            "UPDATE skill_candidates SET status = 'imported' WHERE status = 'candidate' AND package_dir = ?",
            (path,),
        )
        return cur.rowcount if cur is not None else 0
