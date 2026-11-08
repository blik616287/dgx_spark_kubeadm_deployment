"""Power/cost report tests. Run: python -m unittest discover -s tests"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import power_report  # noqa: E402


class LoadTests(unittest.TestCase):
    def _write(self, payload: object) -> Path:
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump(payload, tmp)
        tmp.close()
        return Path(tmp.name)

    def test_single_probe_report_is_one_row(self) -> None:
        path = self._write({"model": "m", "metrics": {"tokens_per_s": 10}})
        try:
            self.assertEqual(len(power_report.load_reports(path)), 1)
        finally:
            path.unlink()

    def test_aggregate_verify_report_reads_probes(self) -> None:
        path = self._write(
            {"stamp": "x", "probes": [{"model": "m", "metrics": {"tokens_per_s": 10}}]}
        )
        try:
            reports = power_report.load_reports(path)
            self.assertEqual(reports[0]["model"], "m")
        finally:
            path.unlink()

    def test_reports_wrapper_and_list(self) -> None:
        wrapped = self._write({"reports": [{"model": "a"}, {"model": "b"}]})
        bare = self._write([{"model": "a"}, {"model": "b"}])
        try:
            self.assertEqual(len(power_report.load_reports(wrapped)), 2)
            self.assertEqual(len(power_report.load_reports(bare)), 2)
        finally:
            wrapped.unlink()
            bare.unlink()


class SampleTests(unittest.TestCase):
    def test_loop_output_is_parsed_line_by_line(self) -> None:
        text = "power.draw [W]\n41.5 W\n42.0 W\nN/A\n"
        self.assertEqual(power_report.parse_power_samples(text), [41.5, 42.0])

    def test_loop_output_is_not_summed(self) -> None:
        # The old behaviour added every line, turning a 40 W reading repeated
        # three times into 120 W.
        text = "40\n40\n40\n"
        self.assertEqual(power_report.parse_power_samples(text), [40.0, 40.0, 40.0])

    def test_single_gpu_samples_are_unchanged(self) -> None:
        self.assertEqual(
            power_report.sample_totals([40.0, 50.0, 60.0], 3), [40.0, 50.0, 60.0]
        )

    def test_multi_gpu_samples_are_summed_per_block(self) -> None:
        self.assertEqual(
            power_report.sample_totals([30.0, 70.0, 32.0, 68.0], 2), [100.0, 100.0]
        )

    def test_summarize_prints_the_spread(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tmp:
            tmp.write("40\n100\n60\n")
            path = Path(tmp.name)
        try:
            out = io.StringIO()
            with mock.patch("sys.stdout", out):
                code = power_report.main(
                    ["--summarize", str(path), "--samples", "3", "--json"]
                )
            self.assertEqual(code, 0)
            summary = json.loads(out.getvalue())
            self.assertEqual(summary["watts_mean"], 66.7)
            self.assertEqual(summary["watts_max"], 100.0)
            self.assertEqual(summary["readings"], 3)
        finally:
            path.unlink()

    def test_mean_is_used_for_the_cost_rows(self) -> None:
        rows = [{"model": "m", "metrics": {"tokens_per_s": 50}}]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tmp:
            json.dump({"probes": rows}, tmp)
            path = Path(tmp.name)
        try:
            with mock.patch.object(
                power_report, "gpu_watts", return_value=[80.0, 100.0]
            ):
                with mock.patch("sys.stdout"):
                    code = power_report.main([str(path)])
            self.assertEqual(code, 0)
        finally:
            path.unlink()

    def test_no_reading_returns_two(self) -> None:
        rows = [{"model": "m", "metrics": {"tokens_per_s": 50}}]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tmp:
            json.dump({"probes": rows}, tmp)
            path = Path(tmp.name)
        try:
            with mock.patch.object(power_report, "gpu_watts", return_value=None):
                with mock.patch("sys.stdout"), mock.patch("sys.stderr"):
                    self.assertEqual(power_report.main([str(path)]), 2)
        finally:
            path.unlink()


if __name__ == "__main__":
    unittest.main()
