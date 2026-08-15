from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading


class PreseedError(RuntimeError):
    """Raised when the preseed HTTP server fails."""


class _PreseedHandler(BaseHTTPRequestHandler):
    directory: Path | None = None

    def do_GET(self) -> None:
        if self.directory is None:
            self.send_error(500)
            return

        requested = self.path.split("?", 1)[0].lstrip("/")

        if not requested:
            self.send_error(404)
            return

        root = self.directory.resolve()
        target = (root / requested).resolve()

        try:
            target.relative_to(root)
        except ValueError:
            self.send_error(403)
            return

        if not target.is_file():
            self.send_error(404)
            return

        try:
            data = target.read_bytes()
        except OSError:
            self.send_error(500)
            return

        self.send_response(200)
        self.send_header(
            "Content-Type",
            "text/plain; charset=utf-8",
        )
        self.send_header(
            "Content-Length",
            str(len(data)),
        )
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args) -> None:
        print(f"[PRESEED] {self.client_address[0]} - {format % args}")


class PreseedServer:
    def __init__(
        self,
        directory: Path,
        host: str = "0.0.0.0",
        port: int = 0,
        guest_host: str = "10.0.2.2",
    ):
        self.directory = Path(directory)
        self.host = host
        self.requested_port = port
        self.guest_host = guest_host

        self._server = None
        self._thread = None

    @property
    def port(self) -> int:
        if self._server is None:
            raise RuntimeError("Preseed server is not running")

        return self._server.server_address[1]

    def start(self) -> None:
        if not self.directory.is_dir():
            raise FileNotFoundError(
                f"Preseed directory does not exist: {self.directory}"
            )

        handler = type(
            "PreseedRequestHandler",
            (_PreseedHandler,),
            {"directory": self.directory},
        )

        self._server = ThreadingHTTPServer(
            (self.host, self.requested_port),
            handler,
        )

        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
        )

        self._thread.start()

        print(f"[+] Preseed server listening on {self.host}:{self.port}")

    def stop(self) -> None:
        if self._server is None:
            return

        self._server.shutdown()
        self._server.server_close()

        if self._thread is not None:
            self._thread.join(timeout=2)

        self._server = None
        self._thread = None

    def url(self, filename: str) -> str:
        return f"http://{self.guest_host}:{self.port}/{filename}"

    def __enter__(self) -> "PreseedServer":
        self.start()
        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ) -> None:
        self.stop()
