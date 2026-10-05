"""Run real dropdowns against an HTTP request trap, once per Qt style."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import struct
import zlib


def serve(connection):
    requests = []
    def chunk(kind, data):
        return struct.pack("!I", len(data)) + kind + data + struct.pack("!I", zlib.crc32(kind + data))
    pixel = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack("!2I5B", 1, 1, 8, 2, 0, 0, 0))
             + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff")) + chunk(b"IEND", b""))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(pixel)))
            self.end_headers()
            self.wfile.write(pixel)

        def log_message(self, *_):
            pass

    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        server.timeout = 0.1
        connection.send(server.server_port)
        while not connection.poll():
            server.handle_request()
        connection.recv()
        connection.send(requests)


def run_style():
    from PySide6.QtCore import QObject, Slot
    from PySide6.QtQml import QQmlEngine
    from PySide6.QtQuickTest import QUICK_TEST_MAIN_WITH_SETUP

    # A separate process keeps the HTTP trap responsive while Qt owns the GIL.
    connection, child = multiprocessing.Pipe()
    server = multiprocessing.Process(target=serve, args=(child,), daemon=True)
    server.start()
    port = connection.recv()

    class Setup(QObject):
        @Slot(QQmlEngine)
        def qmlEngineAvailable(self, engine):
            engine.rootContext().setContextProperty("testPixelUrl", f"http://127.0.0.1:{port}/pixel.png")

    root = Path(__file__).resolve().parent
    try:
        result = QUICK_TEST_MAIN_WITH_SETUP("plaintext", Setup, ["plaintext", "-import", str(root / "qml/imports"),
                                                               "-input", str(root / "qml/tst_plaintext.qml")])
    finally:
        connection.send("stop")
        requests = connection.recv()
        server.join()
    if requests != ["/control.png"]:
        print(f"FAIL: expected only the positive-control image request; got {requests}", file=sys.stderr)
        return 1
    print(f"{os.environ['QT_QUICK_CONTROLS_STYLE']}: HTTP monitor saw the positive control and zero metadata image requests")
    return result


if __name__ == "__main__":
    if "--style-child" in sys.argv:
        sys.exit(run_style())
    for style in ("Basic", "Fusion"):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software", QT_QUICK_CONTROLS_STYLE=style)
        subprocess.run([sys.executable, __file__, "--style-child"], env=env, check=True, timeout=60)
