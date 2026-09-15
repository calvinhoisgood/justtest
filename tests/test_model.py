import unittest

from justtest_observability.model import TelemetryRecord


class TelemetryRecordTests(unittest.TestCase):
    def test_normalizes_kind_and_tags(self) -> None:
        record = TelemetryRecord(
            kind=" LOG ",
            name="app.message",
            payload={"message": "hello"},
            tags={" env ": " prod ", "region": "sg"},
        )
        self.assertEqual(record.kind, "log")
        self.assertEqual(record.tags, {"env": "prod", "region": "sg"})

    def test_rejects_unknown_kind(self) -> None:
        with self.assertRaises(ValueError):
            TelemetryRecord(kind="unknown", name="x", payload={})


if __name__ == "__main__":
    unittest.main()
