from __future__ import annotations

import importlib.util
import json
from itertools import chain
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


def load_script(name: str):
    path = ROOT / "Infra" / "spark" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ShuffleCanaryContractTest(unittest.TestCase):
    def test_rejects_a_single_source_host(self):
        canary = load_script("shuffle_canary")
        result = canary.summarize_result(
            [
                (0, 2, 2, ("data-host",)),
                (1, 2, 4, ("data-host",)),
            ],
            total_rows=4,
            expected_groups=2,
            min_hosts=2,
        )

        self.assertIs(result["rows_match"], True)
        self.assertIs(result["sum_match"], True)
        self.assertIs(result["hosts_match"], False)
        self.assertEqual(
            canary.validation_errors(result),
            ["too few executor hosts participated in the shuffle map stage"],
        )

    def test_accepts_two_source_hosts(self):
        canary = load_script("shuffle_canary")
        result = canary.summarize_result(
            [
                (0, 2, 2, ("data-host", "service-host")),
                (1, 2, 4, ("data-host", "service-host")),
            ],
            total_rows=4,
            expected_groups=2,
            min_hosts=2,
        )

        self.assertEqual(result["source_hosts"], ["data-host", "service-host"])
        self.assertIs(result["hosts_match"], True)
        self.assertEqual(canary.validation_errors(result), [])


class DatasetDigestContractTest(unittest.TestCase):
    def setUp(self):
        self.digest = load_script("dataset_digest")

    def test_integer_and_string_have_different_digests(self):
        int_schema = '{"fields":[{"name":"v","nullable":true,"type":"integer"}],"type":"struct"}'
        string_schema = '{"fields":[{"name":"v","nullable":true,"type":"string"}],"type":"struct"}'

        self.assertNotEqual(
            self.digest.content_digest(int_schema, ['{"v":1}']),
            self.digest.content_digest(string_schema, ['{"v":"1"}']),
        )

    def test_null_and_literal_null_sentinel_have_different_digests(self):
        schema = '{"fields":[{"name":"v","nullable":true,"type":"string"}],"type":"struct"}'

        self.assertNotEqual(
            self.digest.content_digest(schema, [json.dumps({"v": None})]),
            self.digest.content_digest(schema, [json.dumps({"v": "\\N"})]),
        )

    def test_control_characters_cannot_move_a_field_boundary(self):
        separator = chr(31)
        schema = '{"fields":[{"name":"a","type":"string"},{"name":"b","type":"string"}],"type":"struct"}'
        left = json.dumps({"a": "x" + separator + "y", "b": "z"}, sort_keys=True)
        right = json.dumps({"a": "x", "b": "y" + separator + "z"}, sort_keys=True)

        self.assertNotEqual(
            self.digest.content_digest(schema, [left]),
            self.digest.content_digest(schema, [right]),
        )

    def test_row_order_does_not_change_the_digest(self):
        schema = '{"fields":[{"name":"v","type":"integer"}],"type":"struct"}'
        rows = ['{"v":1}', '{"v":2}']

        self.assertEqual(
            self.digest.content_digest(schema, rows),
            self.digest.content_digest(schema, reversed(rows)),
        )

    def test_ordered_stream_matches_compatibility_digest(self):
        schema = '{"fields":[{"name":"v","type":"integer"}],"type":"struct"}'
        rows = ['{"v":3}', '{"v":1}', '{"v":2}', '{"v":2}']

        self.assertEqual(
            self.digest.content_digest(schema, rows),
            self.digest.content_digest_ordered(schema, iter(sorted(rows))),
        )

    def test_partition_boundaries_do_not_change_ordered_stream_digest(self):
        schema = '{"fields":[{"name":"v","type":"integer"}],"type":"struct"}'
        rows = sorted([f'{{"v":{value}}}' for value in [9, 1, 7, 3, 5, 2, 8, 4, 6]])
        expected = self.digest.content_digest_ordered(schema, iter(rows))

        for partition_count in [1, 2, 3, 5, 8]:
            partitions = [
                rows[
                    (len(rows) * index) // partition_count :
                    (len(rows) * (index + 1)) // partition_count
                ]
                for index in range(partition_count)
            ]
            streamed = chain.from_iterable(partitions)
            self.assertEqual(
                expected, self.digest.content_digest_ordered(schema, streamed)
            )

    def test_weekly_digest_path_streams_instead_of_collecting(self):
        source = (
            ROOT / "Infra" / "spark" / "jobs" / "repo_activity_weekly.py"
        ).read_text(encoding="utf-8")
        start = source.index("def slice_row_digest")
        end = source.index(chr(10) + "def _hadoop_path_exists", start)
        digest_block = source[start:end]

        self.assertNotIn("rendered.collect()", digest_block)
        self.assertIn("toLocalIterator()", digest_block)


if __name__ == "__main__":
    unittest.main()
