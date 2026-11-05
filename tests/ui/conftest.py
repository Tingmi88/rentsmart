"""Browser tests: the real local app on 127.0.0.1, driven by Playwright's Chromium.

The server runs in a thread of the test process, so the autouse respx mock in
tests/conftest.py still intercepts every RentCast call. Run with `pytest -m ui`.
"""

import socket
import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn

from rentsmart.web.app import create_app
from tests.conftest import TODAY


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def app_url(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """A fresh local UI server per test, on its own port and (via no_live_http) its own cache."""
    monkeypatch.setenv("RENTCAST_API_KEY", "test-key-SECRET")
    port = _free_port()
    config = uvicorn.Config(
        create_app(port, today=lambda: TODAY), host="127.0.0.1", port=port, log_level="warning"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("local UI server did not start")
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)
