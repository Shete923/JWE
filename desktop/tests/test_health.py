import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

from app.health import check_backend, normalize_base_url


class HealthHandler(BaseHTTPRequestHandler):
    responses: ClassVar[dict[str, tuple[int, dict[str, object]]]] = {}

    def do_GET(self) -> None:
        status_code, payload = self.responses[self.path]
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


class BackendHealthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), HealthHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def test_reports_api_and_database_online(self) -> None:
        HealthHandler.responses = {
            "/health": (200, {"status": "ok"}),
            "/health/db": (200, {"status": "ok", "database": "ok"}),
        }

        result = check_backend(self.base_url)

        self.assertEqual(result.overall_state, "online")
        self.assertEqual(result.api.state, "online")
        self.assertEqual(result.database.state, "online")

    def test_reports_database_unavailable(self) -> None:
        HealthHandler.responses = {
            "/health": (200, {"status": "ok"}),
            "/health/db": (
                503,
                {"detail": "DATABASE_URL is not configured."},
            ),
        }

        result = check_backend(self.base_url)

        self.assertEqual(result.overall_state, "degraded")
        self.assertEqual(result.api.state, "online")
        self.assertEqual(result.database.state, "degraded")
        self.assertEqual(result.database.message, "DATABASE_URL is not configured.")

    def test_rejects_credentials_in_backend_url(self) -> None:
        with self.assertRaisesRegex(ValueError, "Do not include a username"):
            normalize_base_url("http://user:password@localhost:8000")


if __name__ == "__main__":
    unittest.main()
