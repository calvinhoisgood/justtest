import unittest
from unittest.mock import MagicMock, patch

from justtest_observability.cli import _parser, main


class CLIAuthTests(unittest.TestCase):
    def test_parser_accepts_transport_authentication_options(self) -> None:
        serve = _parser().parse_args(["serve", "--auth-token", "local-secret"])
        self.assertEqual(serve.auth_token, "local-secret")

        forward = _parser().parse_args(
            ["forward", "--endpoint", "https://example.test/v1/telemetry", "--bearer-token", "remote-secret"]
        )
        self.assertEqual(forward.bearer_token, "remote-secret")

        agent = _parser().parse_args(
            ["agent", "--forward-url", "https://example.test/v1/telemetry", "--forward-bearer-token", "remote-secret"]
        )
        self.assertEqual(agent.forward_bearer_token, "remote-secret")

    @patch("justtest_observability.cli.build_server")
    def test_serve_passes_auth_token_to_http_server(self, build_server: MagicMock) -> None:
        server = build_server.return_value
        server.server_port = 8127
        server.serve_forever.side_effect = KeyboardInterrupt

        self.assertEqual(main(["serve", "--auth-token", "local-secret"]), 0)
        self.assertEqual(build_server.call_args.kwargs["auth_token"], "local-secret")
        server.server_close.assert_called_once_with()

    @patch("justtest_observability.cli.DurableHTTPForwarder")
    def test_forward_passes_bearer_token(self, forwarder_type: MagicMock) -> None:
        forwarder = forwarder_type.return_value
        forwarder.consumer = "default-http"
        forwarder.forward_once.return_value = 0

        self.assertEqual(
            main(
                [
                    "forward",
                    "--endpoint",
                    "https://example.test/v1/telemetry",
                    "--bearer-token",
                    "remote-secret",
                    "--once",
                ]
            ),
            0,
        )
        self.assertEqual(forwarder_type.call_args.kwargs["bearer_token"], "remote-secret")


if __name__ == "__main__":
    unittest.main()
