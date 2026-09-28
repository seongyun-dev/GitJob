"""Submit an existing completion event: python -m worker.submit --kind ... --input ..."""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from worker.client import (
    MAX_REQUEST_BYTES,
    CompletionClient,
    CompletionKind,
    SubmissionError,
    validate_submission,
)


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse normally echoes unknown arguments, which might contain an
        # accidentally supplied secret. This CLI only accepts token via env.
        raise ValueError("INVALID_SUBMISSION_ARGUMENTS")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _Parser(
        description="Submit a completed A/B event to the internal C service"
    )
    parser.add_argument(
        "--kind", required=True, choices=[kind.value for kind in CompletionKind]
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--timeout-seconds", default=10.0, type=float)
    parser.add_argument("--max-attempts", default=3, type=int)
    try:
        arguments = parser.parse_args(argv)
        if not arguments.input.is_file():
            raise ValueError("COMPLETION_INPUT_FILE_REQUIRED")
        with arguments.input.open("rb") as handle:
            body = handle.read(MAX_REQUEST_BYTES + 1)
        if len(body) > MAX_REQUEST_BYTES:
            raise ValueError("COMPLETION_INPUT_TOO_LARGE")
        kind, event = validate_submission(arguments.kind, json.loads(body))
        client = CompletionClient(
            os.getenv("C_COMPUTE_URL", ""),
            os.getenv("C_COMPUTE_TOKEN", ""),
            timeout_seconds=arguments.timeout_seconds,
            max_attempts=arguments.max_attempts,
        )
        receipt = client.submit(kind, event)
    except SubmissionError as error:
        print(
            json.dumps(
                {
                    "code": error.code,
                    "status": "NOT_COMPLETED",
                    "attempts": error.attempts,
                    "status_code": error.status_code,
                }
            ),
            file=sys.stderr,
        )
        return 1
    except (ValueError, OSError, UnicodeError):
        print(
            json.dumps(
                {
                    "code": "INVALID_SUBMISSION_INPUT_OR_CONFIG",
                    "status": "NOT_COMPLETED",
                }
            ),
            file=sys.stderr,
        )
        return 2
    except Exception:  # noqa: BLE001 - CLI boundary must not print upstream secrets.
        print(
            json.dumps({"code": "SUBMISSION_FAILED", "status": "NOT_COMPLETED"}),
            file=sys.stderr,
        )
        return 1
    print(receipt.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
