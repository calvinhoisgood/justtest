import unittest

from justtest_observability.collectors.host import HostCollector, HostSnapshot, _parse_linux_meminfo


class HostCollectorTests(unittest.TestCase):
    def test_parses_linux_meminfo_bytes(self) -> None:
        values = _parse_linux_meminfo("MemTotal: 1024 kB\nMemAvailable: 256 kB\n")
        self.assertEqual(values["MemTotal"], 1024 * 1024)
        self.assertEqual(values["MemAvailable"], 256 * 1024)

    def test_emits_available_snapshot_values(self) -> None:
        collector = HostCollector(
            lambda: HostSnapshot(
                logical_cpu_count=8,
                memory_total_bytes=1000,
                memory_available_bytes=400,
                uptime_seconds=12.5,
                load_1=0.5,
            )
        )
        metrics = {record.name: record.payload["value"] for record in collector.collect()}
        self.assertEqual(metrics["system.cpu.logical_count"], 8)
        self.assertEqual(metrics["system.memory.used_bytes"], 600)
        self.assertEqual(metrics["system.uptime.seconds"], 12.5)
        self.assertEqual(metrics["system.load.1"], 0.5)
        self.assertNotIn("system.load.5", metrics)


if __name__ == "__main__":
    unittest.main()
