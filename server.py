#!/usr/bin/env python3
"""OpenKey dev server — serves static files and proxies /api/* to the
NVIDIA NIM API so the browser never hits CORS restrictions."""
import http.server
import socketserver
import urllib.request
import urllib.error
import ssl

PORT = 8000
UPSTREAM = "https://integrate.api.nvidia.com"
HOP_BY_HOP = {"connection", "keep-alive", "transfer-encoding", "content-encoding", "content-length"}


class Handler(http.server.SimpleHTTPRequestHandler):
    def _proxy(self, method):
        path = self.path[len("/api"):]  # strip the /api prefix
        url = UPSTREAM + path
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None

        req = urllib.request.Request(url, data=body, method=method)
        for name, value in self.headers.items():
            if name.lower() in ("host", "content-length", "connection"):
                continue
            req.add_header(name, value)

        try:
            resp = urllib.request.urlopen(req, timeout=300)
            status = resp.status
            headers = resp.headers
            stream = resp
        except urllib.error.HTTPError as e:
            status = e.code
            headers = e.headers
            stream = e
        except Exception as e:
            self.send_error(502, f"Upstream error: {e}")
            return

        self.send_response(status)
        for name, value in headers.items():
            if name.lower() in HOP_BY_HOP:
                continue
            self.send_header(name, value)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        # stream the body through (works for SSE too)
        while True:
            chunk = stream.read(4096)
            if not chunk:
                break
            try:
                self.wfile.write(chunk)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                break

    def do_GET(self):
        if self.path.startswith("/api/"):
            self._proxy("GET")
        else:
            super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/"):
            self._proxy("POST")
        else:
            self.send_error(405)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, Accept")
        self.end_headers()

    def log_message(self, fmt, *args):
        pass  # quiet


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    with Server(("", PORT), Handler) as httpd:
        print(f"OpenKey running at http://localhost:{PORT}")
        httpd.serve_forever()
