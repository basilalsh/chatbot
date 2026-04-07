import os
import socket
import threading
import time
from contextlib import closing
from pathlib import Path

import webview
from werkzeug.serving import make_server


def _find_free_port(host: str = "127.0.0.1") -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind((host, 0))
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return int(sock.getsockname()[1])


class FlaskServerThread(threading.Thread):
    def __init__(self, app, host: str, port: int):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self._server = make_server(host, port, app, threaded=True)

    def run(self):
        self._server.serve_forever()

    def shutdown(self):
        self._server.shutdown()


def _wait_until_port_open(host: str, port: int, timeout_sec: float = 20.0) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex((host, port)) == 0:
                return True
        time.sleep(0.15)
    return False


def main():
    project_dir = Path(__file__).resolve().parent
    os.chdir(project_dir)

    from app import create_app

    host = "127.0.0.1"
    port = _find_free_port(host)
    flask_app = create_app()
    server_thread = FlaskServerThread(flask_app, host, port)
    server_thread.start()

    if not _wait_until_port_open(host, port):
        raise RuntimeError("Failed to start embedded backend server.")

    url = f"http://{host}:{port}"
    window = webview.create_window(
        title="Dhofar Insurance Enterprise AI Assistant",
        url=url,
        width=1300,
        height=860,
        min_size=(1024, 700),
    )

    def on_closed():
        server_thread.shutdown()

    window.events.closed += on_closed
    webview.start(debug=False)


if __name__ == "__main__":
    main()
