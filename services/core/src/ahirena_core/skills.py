"""Yetenek paketleri.

Paket `SKILL.md` (ad ve açıklama) ile uygulamaya özgü `capabilities.json` taşır.
`capabilities.json` Agent Skills veya MCP standardının parçası değildir.
Paket metni izin veremez: istenen araç ile kullanıcının verdiği izin ayrıdır.
Betik çalıştırılmaz; yalnızca denetlenmiş araçlar vardır.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from pathlib import Path

from .db import Database, utcnow
from .filesafe import FileRejected, read_inside, validate_root
from .sqlguard import PROBE_SQL, TABLES_SQL, SqlRejected, assert_readonly

AUDITED_TOOLS = ("clock.now", "files.read", "sql.query", "sql.tables")
_NAME = re.compile(r"^[a-z0-9-]{1,40}$")


class SkillError(ValueError):
    pass


def parse_skill_md(text: str) -> tuple[str, str, str]:
    if not text.startswith("---"):
        raise SkillError("SKILL.md '---' ön bilgisiyle başlamalı.")
    end = text.find("\n---", 3)
    if end < 0:
        raise SkillError("SKILL.md ön bilgisi kapanmamış.")
    meta: dict[str, str] = {}
    for line in text[3:end].splitlines():
        if not line.strip():
            continue
        if ":" not in line:
            raise SkillError(f"Ön bilgi satırı anlaşılamadı: {line}")
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip('"').strip("'")
    name = meta.get("name", "")
    description = meta.get("description", "")
    if not _NAME.match(name):
        raise SkillError("name yalnızca küçük harf, rakam ve tire olabilir (en fazla 40).")
    if not description or len(description) > 400:
        raise SkillError("description 1–400 karakter olmalı.")
    return name, description, text[end + 4 :].strip()


def parse_capabilities(text: str) -> list[str]:
    try:
        data = json.loads(text)
    except ValueError as e:
        raise SkillError(f"capabilities.json okunamadı: {e}") from e
    if data.get("format") != "ahirena-capabilities" or data.get("version") != 1:
        raise SkillError("capabilities.json formatı ahirena-capabilities sürüm 1 olmalı.")
    if data.get("network") not in (None, "none"):
        raise SkillError("Bu aşamada ağ izni verilemez.")
    tools = data.get("tools")
    if not isinstance(tools, list) or not tools or len(tools) > 8:
        raise SkillError("En az bir, en fazla sekiz araç yazılmalı.")
    unknown = [t for t in tools if t not in AUDITED_TOOLS]
    if unknown:
        raise SkillError(
            "Denetlenmemiş araç istenmiş: "
            + ", ".join(map(str, unknown))
            + ". Betik ve kabuk çalıştırma kapalı."
        )
    return list(dict.fromkeys(tools))


def package_hash(skill_md: str, capabilities: str) -> str:
    h = hashlib.sha256()
    h.update(skill_md.encode("utf-8"))
    h.update(b"\0")
    h.update(capabilities.encode("utf-8"))
    return h.hexdigest()


class SkillRegistry:
    def __init__(self, db: Database, data_dir: Path):
        self.db = db
        self.root = data_dir / "skills"

    def list(self) -> list[dict]:
        rows = self.db.query("SELECT * FROM skills ORDER BY name")
        return [self._row(r) for r in rows]

    def get(self, skill_id: str) -> dict:
        row = self.db.query_one("SELECT * FROM skills WHERE id = ?", (skill_id,))
        if not row:
            raise SkillError("Yetenek bulunamadı.")
        return self._row(row)

    def import_dir(self, source: str) -> dict:
        src = Path(source).expanduser().resolve()
        skill_path = src / "SKILL.md"
        cap_path = src / "capabilities.json"
        if not skill_path.is_file() or not cap_path.is_file():
            raise SkillError("Klasörde SKILL.md ve capabilities.json olmalı.")
        skill_md = skill_path.read_text(encoding="utf-8-sig")
        cap_text = cap_path.read_text(encoding="utf-8-sig")
        name, description, _body = parse_skill_md(skill_md)
        tools = parse_capabilities(cap_text)
        digest = package_hash(skill_md, cap_text)
        existing = self.db.query_one("SELECT * FROM skills WHERE id = ?", (name,))
        if existing and existing["content_hash"] == digest:
            return self.get(name)
        dest = self.root / name / digest[:12]
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        (dest / "SKILL.md").write_text(skill_md, encoding="utf-8")
        (dest / "capabilities.json").write_text(cap_text, encoding="utf-8")
        now = utcnow()
        with self.db.transaction() as c:
            if existing:
                self._archive_row(c, existing, now)
                try:
                    next_ver = str(int(str(existing["version"])) + 1)
                except ValueError:
                    next_ver = f"{existing['version']}+1"
                c.execute(
                    """UPDATE skills SET version=?, description=?, enabled=0, package_dir=?, content_hash=?, tools_json=?,
                              last_test_json=NULL, created_at=?
                       WHERE id=?""",
                    (next_ver, description, str(dest), digest, json.dumps(tools), now, name),
                )
                c.execute("DELETE FROM skill_grants WHERE skill_id = ?", (name,))
            else:
                c.execute(
                    """INSERT INTO skills (id, version, name, description, enabled, package_dir, content_hash, tools_json, created_at)
                       VALUES (?, '1', ?, ?, 0, ?, ?, ?, ?)""",
                    (name, name, description, str(dest), digest, json.dumps(tools), now),
                )
        from .skilldraft import mark_imported_by_path

        mark_imported_by_path(self.db, str(src))
        return self.get(name)

    def list_versions(self, skill_id: str) -> dict:
        skill = self.get(skill_id)
        by_hash: dict[str, dict] = {}
        for row in self.db.query(
            "SELECT * FROM skill_versions WHERE skill_id = ? ORDER BY archived_at DESC",
            (skill_id,),
        ):
            by_hash[row["content_hash"]] = {
                "content_hash": row["content_hash"],
                "version": row["version"],
                "description": row["description"],
                "package_dir": row["package_dir"],
                "tools": json.loads(row["tools_json"]),
                "active": False,
                "exists": Path(row["package_dir"]).is_dir(),
                "archived_at": row["archived_at"],
            }
        parent = self.root / skill_id
        if parent.is_dir():
            for child in sorted(parent.iterdir()):
                if not child.is_dir():
                    continue
                try:
                    meta = self._read_package(child)
                except SkillError:
                    continue
                if meta["content_hash"] in by_hash:
                    by_hash[meta["content_hash"]]["exists"] = True
                    by_hash[meta["content_hash"]]["package_dir"] = str(child)
                    continue
                if meta["content_hash"] == skill["content_hash"]:
                    continue
                by_hash[meta["content_hash"]] = {
                    "content_hash": meta["content_hash"],
                    "version": "?",
                    "description": meta["description"],
                    "package_dir": str(child),
                    "tools": meta["tools"],
                    "active": False,
                    "exists": True,
                    "archived_at": None,
                }
        active = {
            "content_hash": skill["content_hash"],
            "version": skill["version"],
            "description": skill["description"],
            "package_dir": skill["package_dir"],
            "tools": skill["tools"],
            "active": True,
            "exists": Path(skill["package_dir"]).is_dir() if skill.get("package_dir") else False,
            "archived_at": None,
        }
        by_hash[skill["content_hash"]] = active
        versions = sorted(
            by_hash.values(),
            key=lambda v: (0 if v["active"] else 1, v.get("archived_at") or "", v["content_hash"]),
        )
        return {
            "skill_id": skill_id,
            "versions": versions,
            "note": "Önceki sürüme dönüş izni düşürür; otomatik etkinleştirmez.",
        }

    def rollback(self, skill_id: str, content_hash: str) -> dict:
        skill = self.get(skill_id)
        digest = (content_hash or "").strip()
        if not digest:
            raise SkillError("İçerik özeti gerekli.")
        if digest == skill["content_hash"]:
            return {**self.get(skill_id), "note": "Bu sürüm zaten etkin paket."}
        archived = self.db.query_one(
            "SELECT * FROM skill_versions WHERE skill_id = ? AND content_hash = ?",
            (skill_id, digest),
        )
        package_dir: Path | None = None
        description = ""
        tools: list[str] = []
        version = "1"
        if archived:
            package_dir = Path(archived["package_dir"])
            description = archived["description"]
            tools = json.loads(archived["tools_json"])
            version = archived["version"]
        if package_dir is None or not package_dir.is_dir():
            parent = self.root / skill_id
            if parent.is_dir():
                for child in parent.iterdir():
                    if not child.is_dir():
                        continue
                    try:
                        meta = self._read_package(child)
                    except SkillError:
                        continue
                    if meta["content_hash"] == digest:
                        package_dir = child
                        description = meta["description"]
                        tools = meta["tools"]
                        break
        if package_dir is None or not package_dir.is_dir():
            raise SkillError("Önceki paket klasörü diskte yok.")
        meta = self._read_package(package_dir)
        if meta["content_hash"] != digest:
            raise SkillError("Paket özeti kayıtla uyuşmuyor.")
        description = meta["description"]
        tools = meta["tools"]
        now = utcnow()
        with self.db.transaction() as c:
            current = c.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)).fetchone()
            if current is None:
                raise SkillError("Yetenek bulunamadı.")
            self._archive_row(c, current, now)
            c.execute(
                """UPDATE skills SET version=?, description=?, enabled=0, package_dir=?, content_hash=?, tools_json=?,
                          last_test_json=NULL, created_at=?
                   WHERE id=?""",
                (version, description, str(package_dir), digest, json.dumps(tools), now, skill_id),
            )
            c.execute("DELETE FROM skill_grants WHERE skill_id = ?", (skill_id,))
        out = self.get(skill_id)
        out["note"] = "Önceki sürüme dönüldü; izinler düşürüldü, yetenek kapalı."
        return out

    def validate(self, skill_id: str) -> dict:
        """Paket şemasını ve güvenli duman testlerini çalıştırır; etkinleştirmez."""
        skill = self.get(skill_id)
        package = Path(skill["package_dir"]) if skill.get("package_dir") else None
        if package is None or not package.is_dir():
            raise SkillError("Paket klasörü diskte yok.")
        result = self._validate_package(package, expected_hash=skill["content_hash"], expected_tools=skill["tools"])
        result["skill_id"] = skill_id
        result["enables"] = False
        with self.db.transaction() as c:
            c.execute(
                "UPDATE skills SET last_test_json = ? WHERE id = ?",
                (json.dumps(result, ensure_ascii=False), skill_id),
            )
        return result

    def validate_path(self, source: str) -> dict:
        """İçe aktarılmamış klasörü doğrular; kurmaz ve etkinleştirmez."""
        src = Path(source).expanduser().resolve()
        if not (src / "SKILL.md").is_file() or not (src / "capabilities.json").is_file():
            raise SkillError("Klasörde SKILL.md ve capabilities.json olmalı.")
        result = self._validate_package(src, expected_hash=None, expected_tools=None)
        result["path"] = str(src)
        result["enables"] = False
        return result

    def _validate_package(
        self,
        package: Path,
        *,
        expected_hash: str | None,
        expected_tools: list[str] | None,
    ) -> dict:
        meta = self._read_package(package)
        checks: list[dict] = [
            {"name": "schema", "ok": True, "detail": "SKILL.md ve capabilities.json okundu."},
        ]
        if expected_hash is not None:
            match = meta["content_hash"] == expected_hash
            checks.append(
                {
                    "name": "content_hash",
                    "ok": match,
                    "detail": "Özet eşleşiyor." if match else "Diskteki paket kayıt özetinden farklı.",
                }
            )
        if expected_tools is not None:
            same = list(meta["tools"]) == list(expected_tools)
            checks.append(
                {
                    "name": "tools",
                    "ok": same,
                    "detail": "Araç listesi kayıtla aynı." if same else "Araç listesi değişmiş.",
                }
            )
        tool_results: list[dict] = []
        for tool in meta["tools"]:
            if tool == "clock.now":
                try:
                    def _no_sql(_sql: str) -> dict:
                        raise SkillError("SQL yok")

                    out = self._run("clock.now", {}, {}, _no_sql)
                    tool_results.append({"tool": tool, "status": "passed", "detail": str(out.get("utc", ""))[:40]})
                except Exception as e:  # noqa: BLE001 — duman testi sonucu kaydedilir
                    tool_results.append({"tool": tool, "status": "failed", "detail": str(e)})
            elif tool == "files.read":
                tool_results.append(
                    {"tool": tool, "status": "skipped", "detail": "Canlı test için kök klasör ve izin gerekir."}
                )
            elif tool in ("sql.query", "sql.tables"):
                tool_results.append(
                    {"tool": tool, "status": "skipped", "detail": "Canlı test için SQL bağlantısı ve izin gerekir."}
                )
            else:
                tool_results.append({"tool": tool, "status": "failed", "detail": "Denetlenmemiş araç."})
        failed = any(not c["ok"] for c in checks) or any(t["status"] == "failed" for t in tool_results)
        skipped = any(t["status"] == "skipped" for t in tool_results)
        status = "failed" if failed else ("partial" if skipped else "passed")
        notes = {
            "passed": "Şema ve güvenli duman testleri geçti. Etkinleştirme ayrı adımdır.",
            "partial": "Paket geçerli; bazı araçlar izin sonrası canlı test ister. Etkinleştirilmedi.",
            "failed": "Doğrulama başarısız. Bu sürüm otomatik açılmaz.",
        }
        return {
            "status": status,
            "content_hash": meta["content_hash"],
            "description": meta["description"],
            "tools": meta["tools"],
            "checks": checks,
            "tool_results": tool_results,
            "tested_at": utcnow(),
            "note": notes[status],
        }

    def uninstall(self, skill_id: str) -> dict:
        skill = self.get(skill_id)
        package_dir = Path(skill["package_dir"]) if skill.get("package_dir") else None
        with self.db.transaction() as c:
            c.execute("DELETE FROM skill_grants WHERE skill_id = ?", (skill_id,))
            c.execute("DELETE FROM skill_versions WHERE skill_id = ?", (skill_id,))
            c.execute("DELETE FROM skills WHERE id = ?", (skill_id,))
        root = self.root.resolve()
        skill_root = (self.root / skill_id).resolve()
        try:
            skill_root.relative_to(root)
        except ValueError:
            pass
        else:
            if skill_root.is_dir():
                shutil.rmtree(skill_root, ignore_errors=True)
        if package_dir and package_dir.is_dir():
            try:
                package_dir.resolve().relative_to(root)
            except ValueError:
                pass
            else:
                shutil.rmtree(package_dir, ignore_errors=True)
                parent = package_dir.parent
                if parent.is_dir() and parent != root and not any(parent.iterdir()):
                    shutil.rmtree(parent, ignore_errors=True)
        return {"removed": skill_id, "was_enabled": skill["enabled"]}

    def _archive_row(self, c, row, archived_at: str) -> None:
        c.execute(
            """INSERT INTO skill_versions
               (skill_id, content_hash, version, description, package_dir, tools_json, archived_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(skill_id, content_hash) DO UPDATE SET
                 version=excluded.version,
                 description=excluded.description,
                 package_dir=excluded.package_dir,
                 tools_json=excluded.tools_json,
                 archived_at=excluded.archived_at""",
            (
                row["id"],
                row["content_hash"],
                row["version"],
                row["description"],
                row["package_dir"],
                row["tools_json"],
                archived_at,
            ),
        )

    def _read_package(self, package_dir: Path) -> dict:
        skill_path = package_dir / "SKILL.md"
        cap_path = package_dir / "capabilities.json"
        if not skill_path.is_file() or not cap_path.is_file():
            raise SkillError("Paket dosyaları eksik.")
        skill_md = skill_path.read_text(encoding="utf-8-sig")
        cap_text = cap_path.read_text(encoding="utf-8-sig")
        _name, description, _body = parse_skill_md(skill_md)
        tools = parse_capabilities(cap_text)
        return {
            "description": description,
            "tools": tools,
            "content_hash": package_hash(skill_md, cap_text),
        }

    def set_enabled(self, skill_id: str, enabled: bool, grants: list[dict] | None = None) -> dict:
        skill = self.get(skill_id)
        if not enabled:
            self.db.query("UPDATE skills SET enabled = 0 WHERE id = ?", (skill_id,))
            return self.get(skill_id)
        declared = set(skill["tools"])
        cleaned: list[tuple[str, str]] = []
        for grant in grants or []:
            perm = grant.get("permission")
            if perm not in declared:
                raise SkillError(f"Paket bu aracı istemiyor: {perm}")
            scope = grant.get("scope") or {}
            if perm == "files.read":
                roots = [str(validate_root(p)) for p in (scope.get("roots") or [])]
                if not roots:
                    raise SkillError("files.read için en az bir klasör seçilmeli.")
                scope = {"roots": roots}
            elif perm in ("sql.query", "sql.tables"):
                if scope.get("mode") not in (None, "read"):
                    raise SkillError("SQL izni yalnızca salt okunur olabilir.")
                scope = {"mode": "read"}
            elif perm == "clock.now":
                scope = {}
            else:
                raise SkillError(f"Bilinmeyen izin: {perm}")
            cleaned.append((perm, json.dumps(scope)))
        missing = declared - {p for p, _ in cleaned}
        if missing:
            raise SkillError("Etkinleştirmeden önce istenen her araca izin verilmeli: " + ", ".join(sorted(missing)))
        with self.db.transaction() as c:
            c.execute("DELETE FROM skill_grants WHERE skill_id = ?", (skill_id,))
            c.executemany(
                "INSERT INTO skill_grants (skill_id, permission, scope_json) VALUES (?, ?, ?)",
                [(skill_id, p, s) for p, s in cleaned],
            )
            c.execute("UPDATE skills SET enabled = 1 WHERE id = ?", (skill_id,))
        return self.get(skill_id)

    def call(self, skill_id: str, tool: str, arguments: dict, sql_query) -> dict:
        skill = self.get(skill_id)
        if not skill["enabled"]:
            return self._finish(skill_id, None, tool, False, "Yetenek kapalı; yeni çağrı başlamaz.")
        if tool not in skill["tools"]:
            return self._finish(skill_id, None, tool, False, "Bu araç paketin bildirmediği bir araç.")
        grant = self.db.query_one(
            "SELECT scope_json FROM skill_grants WHERE skill_id = ? AND permission = ?", (skill_id, tool)
        )
        if not grant:
            return self._finish(skill_id, None, tool, False, "Kullanıcı bu araca izin vermemiş.")
        scope = json.loads(grant["scope_json"])
        try:
            result = self._run(tool, arguments or {}, scope, sql_query)
        except (SkillError, FileRejected, SqlRejected) as e:
            return self._finish(skill_id, None, tool, False, str(e))
        done = self._finish(skill_id, None, tool, True, None)
        done["result"] = result
        return done

    def _run(self, tool: str, arguments: dict, scope: dict, sql_query) -> dict:
        if tool == "clock.now":
            return {"utc": utcnow()}
        if tool == "files.read":
            return read_inside(scope.get("roots") or [], str(arguments.get("path") or ""))
        if tool == "sql.tables":
            return sql_query(TABLES_SQL)
        if tool == "sql.query":
            return sql_query(assert_readonly(str(arguments.get("sql") or "")))
        raise SkillError("Araç yok.")

    def _finish(self, skill_id: str | None, mcp_id: str | None, tool: str, ok: bool, error: str | None) -> dict:
        self.db.query(
            "INSERT INTO tool_calls (id, skill_id, mcp_id, tool, ok, error, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), skill_id, mcp_id, tool, int(ok), error, utcnow()),
        )
        return {"ok": ok, "error": error, "tool": tool}

    def _row(self, row) -> dict:
        grants = self.db.query("SELECT permission, scope_json FROM skill_grants WHERE skill_id = ?", (row["id"],))
        last_test = None
        if "last_test_json" in row.keys() and row["last_test_json"]:
            try:
                last_test = json.loads(row["last_test_json"])
            except ValueError:
                last_test = None
        return {
            "id": row["id"],
            "version": row["version"],
            "name": row["name"],
            "description": row["description"],
            "enabled": bool(row["enabled"]),
            "package_dir": row["package_dir"],
            "content_hash": row["content_hash"],
            "tools": json.loads(row["tools_json"]),
            "grants": [{"permission": g["permission"], "scope": json.loads(g["scope_json"])} for g in grants],
            "scripts": "kapalı",
            "last_test": last_test,
        }



def log_mcp_call(db: Database, mcp_id: str, tool: str, ok: bool, error: str | None) -> None:
    db.query(
        "INSERT INTO tool_calls (id, skill_id, mcp_id, tool, ok, error, created_at) VALUES (?, NULL, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), mcp_id, tool, int(ok), error, utcnow()),
    )
