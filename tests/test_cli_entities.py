import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from justtest_observability.cli import _parser, main
from justtest_observability.model import TelemetryRecord
from justtest_observability.storage import SQLiteTelemetryStore


class EntityCLITests(unittest.TestCase):
    def test_entity_query_arguments_are_bounded_by_known_types(self) -> None:
        args = _parser().parse_args(["entities", "--type", "service", "--limit", "25"])
        self.assertEqual(args.entity_type, "service")
        self.assertEqual(args.limit, 25)
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                _parser().parse_args(["entities", "--type", "pod"])

    def test_entities_command_reads_persisted_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "telemetry.db"
            with SQLiteTelemetryStore(database) as store:
                store.append_many(
                    [
                        TelemetryRecord(
                            kind="metric",
                            name="requests",
                            timestamp=50.0,
                            host="node-a",
                            service="checkout",
                            tags={"env": "test"},
                            payload={"value": 1},
                        )
                    ]
                )
            output = io.StringIO()
            with redirect_stdout(output):
                result = main(
                    [
                        "--database",
                        str(database),
                        "entities",
                        "--type",
                        "service",
                    ]
                )
            self.assertEqual(result, 0)
            row = json.loads(output.getvalue())
            self.assertEqual(row["type"], "service")
            self.assertEqual(row["id"], "checkout")
            self.assertEqual(row["tags"]["env"], "test")


if __name__ == "__main__":
    unittest.main()
