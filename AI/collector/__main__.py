"""Collector process entrypoint."""

from collector import app
from common.server import run_health_server


def main() -> None:
    run_health_server(app)


if __name__ == "__main__":
    main()
