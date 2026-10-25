from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

HealthState = Literal["online", "offline", "degraded", "unknown"]


@dataclass(frozen=True)
class ServiceHealth:
    state: HealthState
    message: str
    latency_ms: int | None = None


@dataclass(frozen=True)
class BackendHealth:
    api: ServiceHealth
    database: ServiceHealth
    checked_at: datetime

    @property
    def overall_state(self) -> HealthState:
        if self.api.state == "offline":
            return "offline"
        if self.api.state != "online" or self.database.state != "online":
            return "degraded"
        return "online"


def normalize_base_url(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError("The backend URL is malformed.") from exc

    if parsed.scheme not in {"http", "https"} or not hostname:
        raise ValueError("Enter a valid backend URL, such as http://127.0.0.1:8000.")
    if parsed.username or parsed.password:
        raise ValueError("Do not include a username or password in the backend URL.")
    if parsed.query or parsed.fragment:
        raise ValueError("The backend URL must not contain a query or fragment.")
    if port is not None and not 1 <= port <= 65_535:
        raise ValueError("The backend URL contains an invalid port.")

    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _decode_response(body: bytes) -> dict[str, object]:
    try:
        result = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return result if isinstance(result, dict) else {}


def _probe(
    base_url: str,
    endpoint: str,
    expected: dict[str, str],
    timeout: float,
) -> ServiceHealth:
    request = Request(
        f"{base_url}{endpoint}",
        headers={"Accept": "application/json", "User-Agent": "JewelleryDesktop/0.1"},
    )
    started = time.perf_counter()

    try:
        with urlopen(request, timeout=timeout) as response:
            status_code = response.status
            payload = _decode_response(response.read(32_768))
    except HTTPError as exc:
        with exc:
            payload = _decode_response(exc.read(32_768))
            status_code = exc.code
        message = payload.get("detail")
        if not isinstance(message, str) or not message.strip():
            message = f"Backend returned HTTP {status_code}."
        return ServiceHealth(
            "degraded",
            message.strip()[:180],
            round((time.perf_counter() - started) * 1000),
        )
    except (URLError, TimeoutError, OSError) as exc:
        reason = exc.reason if isinstance(exc, URLError) else exc
        if isinstance(reason, TimeoutError):
            message = "Connection timed out. Confirm the backend is running."
        elif isinstance(reason, ConnectionRefusedError):
            message = "Connection refused. Start the backend and try again."
        else:
            message = "Could not reach the backend. Check its address and try again."
        return ServiceHealth(
            "offline",
            message,
            round((time.perf_counter() - started) * 1000),
        )

    latency_ms = round((time.perf_counter() - started) * 1000)
    if status_code != 200:
        return ServiceHealth(
            "degraded",
            f"Backend returned HTTP {status_code}.",
            latency_ms,
        )
    if any(payload.get(key) != value for key, value in expected.items()):
        return ServiceHealth(
            "degraded",
            "The health endpoint returned an unexpected response.",
            latency_ms,
        )

    return ServiceHealth("online", "Connected and responding normally.", latency_ms)


def check_backend(base_url: str, timeout: float = 3.0) -> BackendHealth:
    """Check the API and its database health endpoint without sending credentials."""
    normalized_url = normalize_base_url(base_url)
    api = _probe(normalized_url, "/health", {"status": "ok"}, timeout)

    if api.state != "online":
        database = ServiceHealth(
            "unknown",
            "Database check skipped because the API is unavailable.",
        )
    else:
        database = _probe(
            normalized_url,
            "/health/db",
            {"status": "ok", "database": "ok"},
            timeout,
        )

    return BackendHealth(api, database, datetime.now().astimezone())
