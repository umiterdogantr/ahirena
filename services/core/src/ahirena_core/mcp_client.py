"""Yerel MCP sunucusu (stdio, Content-Length çerçeve).

Süreç uygulamanın sırlarını miras almaz. Araç listesinin özeti değişince
eski izinler silinir; yeni liste ayrıca onaylanmadan çağrı yapılmaz.
Desteklenen deneme sürümü: 2025-06-18 (test sunucusu). Sunucu başka bir
sürüm bildirirse sürüm kaydedilir, araçlar yine özetlenir.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from .db import Database, utcnow

PROTOCOL = "2025-06-18"
_KEEP_ENV = (
    "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "PATH", "PATHEXT", "COMSPEC",
    "TEMP", "TMP", "LOCALAPPDATA", "APPDATA", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
)


class McpError(RuntimeError):
    pass


def _clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k in _KEEP_ENV}


def _frame(obj: dict) -> bytes:
    body = json.dumps(obj).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


def _read_frame(stream) -> dict:
    length = None
    while True:
        line = stream.readline()
        if not line:
            raise McpError("MCP sunucusu bağlantıyı kapattı.")
        if line in (b"\r\n", b"\n"):
            break
        text = line.decode("ascii", "replace")
        if text.lower().startswith("content-length:"):
            length = int(text.split(":", 1)[1].strip())
    if length is None:
        raise McpError("MCP çerçevesinde Content-Length yok.")
    return json.loads(stream.read(length).decode("utf-8"))


def tools_hash(tools: list[dict]) -> str:
    packed = json.dumps(
        [{"name": t.get("name"), "description": t.get("description"), "inputSchema": t.get("inputSchema")} for t in tools],
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(packed.encode("utf-8")).hexdigest()


class McpRegistry:
    def __init__(self, db: Database):
        self.db = db

    def list(self) -> list[dict]:
        return [self._row(r) for r in self.db.query("SELECT * FROM mcp_servers ORDER BY name")]

    def add(self, name: str, command: str, args: list[str]) -> dict:
        name = name.strip()
        command = command.strip()
        if not name or not command:
            raise McpError("Ad ve komut gerekli.")
        if not Path(command).is_file() and not shutil_which(command):
            raise McpError(f"Komut bulunamadı: {command}")
        server_id = str(uuid.uuid4())
        now = utcnow()
        self.db.query(
            """INSERT INTO mcp_servers
               (id, name, command, args_json, enabled, tools_json, grants_json, updated_at)
               VALUES (?, ?, ?, ?, 0, '[]', '[]', ?)""",
            (server_id, name, command, json.dumps(args), now),
        )
        return self._get(server_id)

    def refresh(self, server_id: str) -> dict:
        row = self._raw(server_id)
        try:
            version, tools = _discover(row["command"], json.loads(row["args_json"]))
            digest = tools_hash(tools)
            grants = json.loads(row["grants_json"])
            revoked = bool(row["tools_hash"] and row["tools_hash"] != digest)
            if revoked:
                grants = []
            self.db.query(
                """UPDATE mcp_servers
                   SET protocol_version=?, tools_hash=?, tools_json=?, grants_json=?, enabled=?, last_error=NULL, updated_at=?
                   WHERE id=?""",
                (version, digest, json.dumps(tools), json.dumps(grants), 0 if revoked else row["enabled"], utcnow(), server_id),
            )
            out = self._get(server_id)
            out["grants_revoked"] = revoked
            return out
        except (McpError, OSError, ValueError) as e:
            self.db.query(
                "UPDATE mcp_servers SET last_error=?, updated_at=? WHERE id=?",
                (str(e), utcnow(), server_id),
            )
            raise McpError(str(e)) from e

    def remove(self, server_id: str) -> dict:
        self._raw(server_id)
        self.db.query("DELETE FROM mcp_servers WHERE id = ?", (server_id,))
        return {"removed": server_id}

    def grant(self, server_id: str, tool: str) -> dict:
        row = self._raw(server_id)
        if not row["tools_hash"]:
            raise McpError("Önce araç listesini yenileyin.")
        names = {t.get("name") for t in json.loads(row["tools_json"])}
        if tool not in names:
            raise McpError("Sunucu bu aracı bildirmiyor.")
        grants = set(json.loads(row["grants_json"]))
        grants.add(tool)
        self.db.query(
            "UPDATE mcp_servers SET grants_json=?, enabled=1, updated_at=? WHERE id=?",
            (json.dumps(sorted(grants)), utcnow(), server_id),
        )
        return self._get(server_id)

    def revoke(self, server_id: str, tool: str) -> dict:
        row = self._raw(server_id)
        grants = [g for g in json.loads(row["grants_json"]) if g != tool]
        self.db.query(
            "UPDATE mcp_servers SET grants_json=?, enabled=?, updated_at=? WHERE id=?",
            (json.dumps(grants), 1 if grants else 0, utcnow(), server_id),
        )
        return self._get(server_id)

    def call(self, server_id: str, tool: str, arguments: dict) -> dict:
        from .skills import log_mcp_call

        row = self._raw(server_id)
        grants = json.loads(row["grants_json"])
        if not row["enabled"] or tool not in grants:
            log_mcp_call(self.db, server_id, tool, False, "İzin yok veya liste değiştiği için onay düştü.")
            return {"ok": False, "error": "İzin yok veya liste değiştiği için onay düştü.", "tool": tool}
        try:
            result = _call(row["command"], json.loads(row["args_json"]), tool, arguments or {})
        except (McpError, OSError, ValueError) as e:
            log_mcp_call(self.db, server_id, tool, False, str(e))
            return {"ok": False, "error": str(e), "tool": tool}
        log_mcp_call(self.db, server_id, tool, True, None)
        return {"ok": True, "error": None, "tool": tool, "result": result}

    def _raw(self, server_id: str):
        row = self.db.query_one("SELECT * FROM mcp_servers WHERE id = ?", (server_id,))
        if not row:
            raise McpError("MCP sunucusu bulunamadı.")
        return row

    def _get(self, server_id: str) -> dict:
        return self._row(self._raw(server_id))

    def _row(self, row) -> dict:
        return {
            "id": row["id"],
            "name": row["name"],
            "command": row["command"],
            "args": json.loads(row["args_json"]),
            "enabled": bool(row["enabled"]),
            "protocol_version": row["protocol_version"],
            "tools_hash": row["tools_hash"],
            "tools": json.loads(row["tools_json"]),
            "grants": json.loads(row["grants_json"]),
            "last_error": row["last_error"],
        }


def shutil_which(command: str) -> str | None:
    from shutil import which

    return which(command)


def _session(command: str, args: list[str]):
    return subprocess.Popen(
        [command, *args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=_clean_env(),
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )


def _exchange(proc, method: str, params: dict, msg_id: int) -> dict:
    assert proc.stdin and proc.stdout
    proc.stdin.write(_frame({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params}))
    proc.stdin.flush()
    msg = _read_frame(proc.stdout)
    if msg.get("error"):
        raise McpError(str(msg["error"]))
    return msg.get("result") or {}


def _discover(command: str, args: list[str]) -> tuple[str, list[dict]]:
    proc = _session(command, args)
    try:
        init = _exchange(
            proc,
            "initialize",
            {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": {"name": "ahirena", "version": "0.1.0"}},
            1,
        )
        assert proc.stdin
        proc.stdin.write(_frame({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        proc.stdin.flush()
        listed = _exchange(proc, "tools/list", {}, 2)
        tools = listed.get("tools") or []
        if not isinstance(tools, list):
            raise McpError("tools/list beklenen listeyi vermedi.")
        return str(init.get("protocolVersion") or ""), tools
    finally:
        proc.kill()
        proc.wait(5)


def _call(command: str, args: list[str], tool: str, arguments: dict) -> dict:
    proc = _session(command, args)
    try:
        _exchange(
            proc,
            "initialize",
            {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": {"name": "ahirena", "version": "0.1.0"}},
            1,
        )
        assert proc.stdin
        proc.stdin.write(_frame({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        proc.stdin.flush()
        result = _exchange(proc, "tools/call", {"name": tool, "arguments": arguments}, 2)
        text = json.dumps(result, ensure_ascii=False)
        if len(text) > 4000:
            text = text[:4000]
        return {"raw": text}
    finally:
        proc.kill()
        proc.wait(5)
