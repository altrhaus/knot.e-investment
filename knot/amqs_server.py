"""AMQS-NDX 로컬 웹서버 — 표준 라이브러리만 쓴다(추가 의존성 없음).

    GET /                 → 대시보드 HTML (4시간 캐시)
    GET /?refresh=1       → 캐시 무시하고 재계산
    GET /api/snapshot.json → 같은 데이터의 원본 JSON
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from .amqs import AmqsNdx
from .amqs_page import render_page


def make_handler(engine: AmqsNdx):
    class Handler(BaseHTTPRequestHandler):
        server_version = "knot.e-AMQS-NDX"

        def _send(self, body: bytes, ctype: str, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            parsed = urlparse(self.path)
            refresh = parse_qs(parsed.query).get("refresh", ["0"])[0] == "1"
            if parsed.path in ("/", "/index.html"):
                snap = engine.snapshot(refresh=refresh)
                self._send(render_page(snap, live=True).encode("utf-8"),
                           "text/html; charset=utf-8")
            elif parsed.path == "/api/snapshot.json":
                snap = engine.snapshot(refresh=refresh)
                self._send(json.dumps(snap, ensure_ascii=False).encode("utf-8"),
                           "application/json; charset=utf-8")
            elif parsed.path == "/healthz":
                self._send(b"ok", "text/plain")
            else:
                self._send(b"not found", "text/plain", 404)

        def log_message(self, fmt, *args):  # 조용한 로그
            return

    return Handler


def serve(engine: AmqsNdx, host: str = "127.0.0.1", port: int = 8765) -> None:
    httpd = ThreadingHTTPServer((host, port), make_handler(engine))
    print(f"AMQS-NDX → http://{host}:{port}/  (Ctrl+C 로 종료)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n종료")
    finally:
        httpd.server_close()
