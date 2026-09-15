import unittest

from justtest_observability.cli import _parser


class DogStatsDCLITests(unittest.TestCase):
    def test_agent_enables_loopback_dogstatsd_by_default(self) -> None:
        args = _parser().parse_args(["agent"])
        self.assertTrue(args.dogstatsd)
        self.assertEqual(args.dogstatsd_host, "127.0.0.1")
        self.assertEqual(args.dogstatsd_port, 8125)

    def test_agent_can_disable_dogstatsd(self) -> None:
        args = _parser().parse_args(["agent", "--no-dogstatsd"])
        self.assertFalse(args.dogstatsd)

    def test_standalone_dogstatsd_defaults_to_loopback(self) -> None:
        args = _parser().parse_args(["dogstatsd"])
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 8125)


if __name__ == "__main__":
    unittest.main()
