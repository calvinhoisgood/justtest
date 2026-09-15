import tempfile
import unittest
from pathlib import Path

from justtest_observability.cli import _dashboard_url, _parser
from justtest_observability.http_server import build_server
from justtest_observability.storage import SQLiteTelemetryStore


class WebUICLITests(unittest.TestCase):
    def test_agent_enables_local_web_ui_by_default(self) -> None:
        args = _parser().parse_args(["agent"])
        self.assertTrue(args.api)
        self.assertEqual(args.api_host, "127.0.0.1")
        self.assertEqual(args.api_port, 8127)
        self.assertFalse(args.open_browser)

    def test_agent_web_ui_can_be_disabled(self) -> None:
        args = _parser().parse_args(["agent", "--no-api"])
        self.assertFalse(args.api)

    def test_dashboard_url_uses_bound_port(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with SQLiteTelemetryStore(Path(temp_dir) / "telemetry.db") as store:
                server = build_server("127.0.0.1", 0, store)
                try:
                    self.assertTrue(_dashboard_url(server).startswith("http://127.0.0.1:"))
                    self.assertTrue(_dashboard_url(server).endswith("/"))
                finally:
                    server.server_close()


if __name__ == "__main__":
    unittest.main()
