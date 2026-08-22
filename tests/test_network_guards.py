"""Tests for the network-exposure guards on user-supplied hosts and URLs."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from deployments.desktop import server  # noqa: E402

coldstart_agent = importlib.import_module("agents.coldstart-agent.main")


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "127.0.0.2", ""])
def test_loopback_hosts_are_recognized(host: str) -> None:
    assert server._is_loopback_host(host) is True


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.5", "10.0.0.1", "example.local"])
def test_non_loopback_hosts_are_recognized(host: str) -> None:
    """Unresolvable hostnames must count as non-loopback, not be assumed safe."""
    assert server._is_loopback_host(host) is False


def test_run_server_refuses_non_loopback_bind_without_opt_in() -> None:
    """The GUI is unauthenticated and can rewrite .env, so this needs intent."""
    with pytest.raises(SystemExit) as excinfo:
        server.run_server(host="0.0.0.0", port=8799, open_browser=False)

    message = str(excinfo.value)
    assert "--allow-remote" in message
    assert ".env" in message


@pytest.mark.parametrize(
    "url",
    [
        # Would make PaperFlow fetch its own unauthenticated settings endpoint.
        "http://127.0.0.1:8765/api/settings",
        "http://localhost:8765/api/settings",
        # Cloud instance metadata.
        "http://169.254.169.254/latest/meta-data/",
        "http://192.168.1.1/admin",
        "http://10.0.0.5/",
        "http://0.0.0.0/",
    ],
)
def test_private_and_loopback_targets_are_refused(url: str) -> None:
    with pytest.raises(ValueError, match="non-public address"):
        coldstart_agent._assert_fetchable_url(url)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "gopher://example.com/", "ftp://example.com/"])
def test_non_http_schemes_are_refused(url: str) -> None:
    with pytest.raises(ValueError, match="unsupported URL scheme"):
        coldstart_agent._assert_fetchable_url(url)


def test_public_urls_are_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A public hostname must pass without the test needing real DNS."""
    import socket

    monkeypatch.setattr(
        coldstart_agent.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )

    coldstart_agent._assert_fetchable_url("https://example.com/~alice")


def test_private_fetch_override_is_honored(monkeypatch: pytest.MonkeyPatch) -> None:
    """Users who host a homepage on the LAN can opt back in explicitly."""
    monkeypatch.setenv("PAPERFLOW_ALLOW_PRIVATE_FETCH", "1")

    coldstart_agent._assert_fetchable_url("http://127.0.0.1:8765/api/settings")


def test_unresolvable_host_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    def boom(*args, **kwargs):
        raise socket.gaierror("nodename nor servname provided")

    monkeypatch.setattr(coldstart_agent.socket, "getaddrinfo", boom)

    with pytest.raises(ValueError, match="cannot resolve host"):
        coldstart_agent._assert_fetchable_url("https://this-host-does-not-exist.invalid/")
