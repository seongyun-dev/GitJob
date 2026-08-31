"""Analysis worker process entrypoint."""

from common.server import run_health_server
from worker import app


def main() -> None:
    run_health_server(app)


if __name__ == "__main__":
    main()
