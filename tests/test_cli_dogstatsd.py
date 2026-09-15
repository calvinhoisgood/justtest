import unittest

from justtest_observability.cli import _parser


class AgentCLITests(unittest.TestCase):
    def test_agent_enables_loopback_dogstatsd_by_default(self) -> None:
        args = _parser().parse_args(["agent"])
        self.assertTrue(args.dogstatsd)
        self.assertEqual(args.dogstatsd_host, "127.0.0.1")
        self.assertEqual(args.dogstatsd_port, 8125)
        self.assertIsNone(args.forward_url)

    def test_agent_can_disable_dogstatsd_and_enable_forwarding(self) -> None:
        args = _parser().parse_args(
            [
                "agent",
                "--no-dogstatsd",
                "--forward-url",
                "http://127.0.0.1:9000/v1/telemetry",
                "--forward-consumer",
                "primary",
            ]
        )
        self.assertFalse(args.dogstatsd)
        self.assertEqual(args.forward_consumer, "primary")
        self.assertEqual(args.forward_batch_size, 500)

    def test_standalone_receivers_and_forwarder_defaults(self) -> None:
        dogstatsd = _parser().parse_args(["dogstatsd"])
        self.assertEqual(dogstatsd.host, "127.0.0.1")
        self.assertEqual(dogstatsd.port, 8125)
        forward = _parser().parse_args(
            ["forward", "--endpoint", "http://127.0.0.1:8127/v1/telemetry", "--once"]
        )
        self.assertTrue(forward.once)
        self.assertEqual(forward.consumer, "default-http")
        self.assertEqual(forward.batch_size, 500)


if __name__ == "__main__":
    unittest.main()
