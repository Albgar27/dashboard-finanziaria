#!/usr/bin/env python3
"""Server locale della dashboard (solo 127.0.0.1).

Serve la cartella docs/ e accetta un solo comando: POST /api/aggiorna-notizie,
che esegue `aggiorna.sh --solo-notizie` (scarica le notizie, rigenera e pubblica la pagina).
Per sicurezza il comando è accettato solo da pagine servite da questo stesso server
(controllo dell'intestazione Origin), uno alla volta e al massimo una volta al minuto.
"""
import json
import subprocess
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOST, PORT = "127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8799
ALLOWED_ORIGINS = {f"http://{HOST}:{PORT}", f"http://localhost:{PORT}"}
LOCK = threading.Lock()
LAST_RUN = [0.0]
MIN_INTERVAL = 60


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):  # niente log per ogni richiesta
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def _json(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/api/aggiorna-notizie":
            return self._json(404, {"ok": False, "errore": "comando sconosciuto"})
        if self.headers.get("Origin") not in ALLOWED_ORIGINS:
            return self._json(403, {"ok": False, "errore": "richiesta non consentita"})
        if time.time() - LAST_RUN[0] < MIN_INTERVAL:
            return self._json(429, {"ok": False, "errore": "aggiornamento appena eseguito, riprova tra un minuto"})
        if not LOCK.acquire(blocking=False):
            return self._json(409, {"ok": False, "errore": "aggiornamento già in corso"})
        try:
            LAST_RUN[0] = time.time()
            r = subprocess.run(["/bin/zsh", str(ROOT / "aggiorna.sh"), "--solo-notizie"], cwd=ROOT,
                               capture_output=True, text=True, timeout=900)
            with open(ROOT / "build.log", "a", encoding="utf-8") as log:
                log.write(r.stdout + r.stderr)
            if r.returncode != 0:
                return self._json(500, {"ok": False, "errore": "aggiornamento non riuscito (vedi build.log)"})
            version = json.loads((ROOT / "docs" / "version.json").read_text(encoding="utf-8"))
            return self._json(200, {"ok": True, "generated_at": version.get("generated_at")})
        except subprocess.TimeoutExpired:
            return self._json(504, {"ok": False, "errore": "aggiornamento troppo lungo"})
        finally:
            LOCK.release()


if __name__ == "__main__":
    handler = partial(Handler, directory=str(ROOT / "docs"))
    ThreadingHTTPServer((HOST, PORT), handler).serve_forever()
