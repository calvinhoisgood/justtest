import unittest

from justtest_observability.model import TelemetryRecord
from justtest_observability.resource import ResourceContext


class ResourceContextTests(unittest.TestCase):
    def test_enriches_host_and_merges_tags_with_record_precedence(self) -> None:
        resource = ResourceContext(host="host-a", tags={"env": "prod", "region": "sg"})
        record = TelemetryRecord(
            kind="metric",
            name="x",
            payload={"value": 1},
            tags={"env": "test"},
        )
        enriched = resource.enrich(record)
        self.assertEqual(enriched.host, "host-a")
        self.assertEqual(enriched.tags, {"env": "test", "region": "sg"})


if __name__ == "__main__":
    unittest.main()
