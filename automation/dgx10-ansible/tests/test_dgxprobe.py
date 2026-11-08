"""Probe helper tests. Run: python -m unittest discover -s tests"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import dgxprobe  # noqa: E402


class KeepAliveTests(unittest.TestCase):
    def test_payload_pins_the_weights(self) -> None:
        payload = dgxprobe.keepalive_payload("qwen3:8b", "-1")
        self.assertEqual(payload["model"], "qwen3:8b")
        self.assertEqual(payload["keep_alive"], "-1")
        # An empty prompt loads the model without generating tokens.
        self.assertEqual(payload["prompt"], "")

    def test_parser_accepts_a_warmup_count(self) -> None:
        args = dgxprobe.build_parser().parse_args(
            ["--deployment", "m-predictor", "--model", "qwen3:8b", "--warmup", "3"]
        )
        self.assertEqual(args.warmup, 3)
        self.assertEqual(args.keep_alive, "-1")

    def test_warmup_defaults_to_two_requests(self) -> None:
        args = dgxprobe.build_parser().parse_args(
            ["--deployment", "m-predictor", "--model", "qwen3:8b"]
        )
        self.assertEqual(args.warmup, 2)


if __name__ == "__main__":
    unittest.main()
