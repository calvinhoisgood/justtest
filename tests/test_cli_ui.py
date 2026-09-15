from justtest_observability.cli import _dashboard_url, _parser
from justtest_observability.http_server import build_server
from justtest_observability.storage import SQLiteTelemetryStore


def test_agent_enables_local_web_ui_by_default():
    args = _parser().parse_args(["agent"])
    assert args.api is True
    assert args.api_host == "127.0.0.1"
    assert args.api_port == 8127
    assert args.open_browser is False


def test_agent_web_ui_can_be_disabled():
    args = _parser().parse_args(["agent", "--no-api"])
    assert args.api is False


def test_dashboard_url_uses_bound_port(tmp_path):
    with SQLiteTelemetryStore(tmp_path / "telemetry.db") as store:
        server = build_server("127.0.0.1", 0, store)
        try:
            assert _dashboard_url(server).startswith("http://127.0.0.1:")
            assert _dashboard_url(server).endswith("/")
        finally:
            server.server_close()
