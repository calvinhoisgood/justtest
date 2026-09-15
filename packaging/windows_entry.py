from __future__ import annotations

import sys

from justtest_observability.cli import main


def entrypoint() -> int:
    argv = sys.argv[1:]
    if not argv:
        # Double-click experience: run the complete local agent and open its dashboard.
        argv = ["agent", "--open-browser"]
    return main(argv)


if __name__ == "__main__":
    raise SystemExit(entrypoint())
