"""Serve disc/ with the cross-origin-isolation headers OPFS sync access handles
and module workers need. Localhost only.  python serve.py  ->  http://127.0.0.1:8097/test.html"""
import http.server, socketserver

PORT = 8097

class H(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

if __name__ == "__main__":
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", PORT), H) as httpd:
        print(f"disc test on http://127.0.0.1:{PORT}/test.html  (COOP/COEP, localhost)")
        httpd.serve_forever()
