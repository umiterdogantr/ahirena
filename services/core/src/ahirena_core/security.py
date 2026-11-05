"""Yerel API koruması (saf ASGI ara katmanı).

- Yalnızca beklenen Host başlıkları kabul edilir (DNS rebinding'e karşı).
- Origin başlığı taşıyan istekler reddedilir: çekirdeği yalnızca masaüstü kabuğunun
  Rust süreci çağırır; tarayıcı kaynaklı istek beklenmez.
- Her istek `Authorization: Bearer <token>` taşımalıdır.
- İstek gövdesi boyut sınırını aşarsa 413 döner.
"""

from __future__ import annotations

import hmac
import json
from typing import Any, Awaitable, Callable

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


async def _reject(send: Send, status: int, message: str) -> None:
    body = json.dumps({"detail": message}, ensure_ascii=False).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json; charset=utf-8"), (b"content-length", str(len(body)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": body})


class LocalGuard:
    def __init__(self, app: Any, token: str, allowed_hosts: Callable[[], set[str]], max_body_bytes: int):
        self.app = app
        self._token = f"Bearer {token}".encode("utf-8")
        self._allowed_hosts = allowed_hosts
        self._max_body = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
                return
            await self.app(scope, receive, send)
            return

        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        host = headers.get(b"host", b"").decode("latin-1")
        if host not in self._allowed_hosts():
            await _reject(send, 403, "Geçersiz Host başlığı.")
            return
        if b"origin" in headers:
            await _reject(send, 403, "Tarayıcı kaynaklı isteklere izin verilmiyor.")
            return
        if not hmac.compare_digest(headers.get(b"authorization", b""), self._token):
            await _reject(send, 401, "Kimlik doğrulama başarısız.")
            return

        declared = headers.get(b"content-length")
        if declared and declared.isdigit() and int(declared) > self._max_body:
            await _reject(send, 413, "İstek gövdesi çok büyük.")
            return

        if scope.get("method") in {"POST", "PUT", "PATCH", "DELETE"}:
            chunks: list[bytes] = []
            size = 0
            while True:
                msg = await receive()
                if msg["type"] == "http.disconnect":
                    return
                body = msg.get("body", b"")
                size += len(body)
                if size > self._max_body:
                    await _reject(send, 413, "İstek gövdesi çok büyük.")
                    return
                chunks.append(body)
                if not msg.get("more_body"):
                    break
            full = b"".join(chunks)
            replayed = False

            async def replay() -> dict[str, Any]:
                nonlocal replayed
                if not replayed:
                    replayed = True
                    return {"type": "http.request", "body": full, "more_body": False}
                return await receive()

            await self.app(scope, replay, send)
            return

        await self.app(scope, receive, send)
