import tempfile
import unittest
from pathlib import Path

from justtest_observability.cli import _parser, _runtime
from justtest_observability.resource import ResourceContext
from justtest_observability.storage import SQLiteTelemetryStore


class OpenMetricsCLITests(unittest.TestCase):
    def test_agent_accepts_multiple_openmetrics_targets(self) -> None:
        args = _parser().parse_args(
            [
                "agent",
                "--openmetrics-url",
                "http://127.0.0.1:9001/metrics",
                "--openmetrics-url",
                "http://127.0.0.1:9002/metrics",
                "--openmetrics-timeout",
                "2.5",
            ]
        )
        self.assertEqual(len(args.openmetrics_url), 2)
        self.assertEqual(args.openmetrics_timeout, 2.5)

    def test_runtime_assigns_unique_names_to_scrape_collectors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with SQLiteTelemetryStore(Path(tmp) / "telemetry.db") as store:
                runtime = _runtime(
                    store,
                    ResourceContext(host="test-host"),
                    openmetrics_urls=[
                        "http://127.0.0.1:9001/metrics",
                        "http://127.0.0.1:9002/metrics",
                    ],
                )
                self.assertEqual(
                    [collector.name for collector in runtime.collectors],
                    ["host", "openmetrics-1", "openmetrics-2"],
                )


if __name__ == "__main__":
    unittest.main()
