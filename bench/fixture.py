"""Smoke-test HTTP app; FAULT_MODE selects normal service, startup crash, or unbounded memory allocation."""
import json
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

mode = os.environ.get("FAULT_MODE", "healthy")
if mode == "crash":
    raise RuntimeError("startup configuration rejected")
if mode == "allocate":
    blocks = []
    while True:
        blocks.append(bytearray(4 * 1024 * 1024))
        print(json.dumps({"event": "allocation", "bytes": len(blocks) * 4194304}), flush=True)
        time.sleep(0.2)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}\n')


HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
