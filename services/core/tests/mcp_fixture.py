"""Testler için tek araçlı MCP sunucusu. AHIRENA_TOKEN ortamda varsa bunu söyler."""

from __future__ import annotations

import json
import os
import sys


def read_frame():
    length = None
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        text = line.decode("ascii", "replace")
        if text.lower().startswith("content-length:"):
            length = int(text.split(":", 1)[1].strip())
    if length is None:
        return None
    return json.loads(sys.stdin.buffer.read(length).decode("utf-8"))


def write_frame(obj: dict) -> None:
    body = json.dumps(obj).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
    sys.stdout.buffer.flush()


TOOL = {
    "name": "yankı",
    "description": "Gönderilen metni geri verir.",
    "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}},
}


def main() -> None:
    extra = "--ikinci" in sys.argv
    tools = [TOOL]
    if extra:
        tools.append({"name": "ikinci", "description": "Yeni araç.", "inputSchema": {"type": "object"}})
    while True:
        msg = read_frame()
        if msg is None:
            return
        method = msg.get("method")
        if method == "initialize":
            write_frame({"jsonrpc": "2.0", "id": msg["id"], "result": {"protocolVersion": "2025-06-18", "capabilities": {}}})
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            write_frame({"jsonrpc": "2.0", "id": msg["id"], "result": {"tools": tools}})
        elif method == "tools/call":
            leaked = "AHIRENA_TOKEN" in os.environ
            text = (msg.get("params") or {}).get("arguments", {}).get("text", "")
            write_frame(
                {
                    "jsonrpc": "2.0",
                    "id": msg["id"],
                    "result": {"content": [{"type": "text", "text": text}], "token_miras": leaked},
                }
            )
        else:
            write_frame({"jsonrpc": "2.0", "id": msg.get("id"), "error": {"code": -32601, "message": method}})


if __name__ == "__main__":
    main()
