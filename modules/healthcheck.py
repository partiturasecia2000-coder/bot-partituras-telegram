import os
import threading
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler

logger = logging.getLogger("TelegramGroupBot")

class CloudHealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Bot Telegram Online 24/7!")

    def log_message(self, format, *args):
        pass

def start_cloud_health_server():
    try:
        # Na Discloud, TYPE=bot não precisa nem deve abrir portas de rede
        if os.getenv("DISCLOUD") or os.getenv("DISCLOUD_APP_ID"):
            return
        port_str = os.getenv("PORT")
        if not port_str or not port_str.isdigit():
            return
        port = int(port_str)
        if port >= 1024:
            server = HTTPServer(("0.0.0.0", port), CloudHealthCheckHandler)
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()
            logger.info(f"Servidor de monitoramento em nuvem ativo na porta {port}")
    except Exception as e:
        logger.warning(f"Health check server ignorado: {e}")
