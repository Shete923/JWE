from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PySide6.QtCore import QObject, QThread, Signal

from app.health import normalize_base_url


class ApiWorker(QThread):
    succeeded = Signal(str, object)
    failed = Signal(str, str)

    def __init__(
        self,
        action_id: str,
        base_url: str,
        method: str,
        path: str,
        payload: Any = None,
        content_type: str = "application/json",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.action_id = action_id
        self.base_url = normalize_base_url(base_url)
        self.method = method
        self.path = path
        self.payload = payload
        self.content_type = content_type

    def run(self) -> None:
        body = None
        headers = {"Accept": "application/json"}
        if self.payload is not None:
            if self.content_type == "application/json":
                body = json.dumps(self.payload).encode("utf-8")
            elif isinstance(self.payload, str):
                body = self.payload.encode("utf-8-sig")
            else:
                self.failed.emit(self.action_id, "Invalid request body.")
                return
            headers["Content-Type"] = self.content_type

        request = Request(
            f"{self.base_url}{self.path}",
            data=body,
            headers=headers,
            method=self.method,
        )
        try:
            with urlopen(request, timeout=12) as response:
                content = response.read(5_000_001)
                if len(content) > 5_000_000:
                    self.failed.emit(
                        self.action_id,
                        "The response is too large to open in the desktop app.",
                    )
                    return
                content_type = response.headers.get_content_type()
        except HTTPError as exc:
            with exc:
                error_body = exc.read(32_768)
            try:
                payload = json.loads(error_body)
            except (json.JSONDecodeError, UnicodeDecodeError):
                payload = {}
            message = payload.get("detail") if isinstance(payload, dict) else None
            if not isinstance(message, str) or not message.strip():
                message = f"Backend returned HTTP {exc.code}."
            self.failed.emit(self.action_id, message.strip()[:500])
            return
        except (URLError, TimeoutError, OSError) as exc:
            self.failed.emit(
                self.action_id,
                "Could not reach the backend. Check that FastAPI is running and the "
                f"backend URL is correct. ({exc.__class__.__name__})",
            )
            return

        if content_type == "text/csv":
            self.succeeded.emit(
                self.action_id, content.decode("utf-8-sig", errors="replace")
            )
            return
        try:
            result = json.loads(content) if content else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.failed.emit(self.action_id, "The backend returned invalid JSON.")
            return
        self.succeeded.emit(self.action_id, result)
