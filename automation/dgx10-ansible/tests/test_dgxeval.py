"""Eval report-card tests. Run: python -m unittest discover -s tests"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import dgxeval  # noqa: E402


class CheckerTests(unittest.TestCase):
    def test_exact_is_case_and_space_insensitive(self) -> None:
        check = dgxeval._exact("DGX10-OK")
        self.assertTrue(check("  dgx10-ok\n"))
        self.assertFalse(check("DGX10-OK, as requested"))

    def test_contains_finds_the_answer_in_prose(self) -> None:
        check = dgxeval._contains("391")
        self.assertTrue(check("17 * 23 = 391"))
        self.assertFalse(check("392"))

    def test_json_shape_requires_every_key(self) -> None:
        check = dgxeval._json_shape(["status", "count"])
        self.assertTrue(check('{"status": "ok", "count": 3}'))
        self.assertFalse(check('{"status": "ok"}'))
        self.assertFalse(check('```json\n{"status": "ok", "count": 3}\n```'))
        self.assertFalse(check('["status", 3]'))


class CaseTests(unittest.TestCase):
    def test_case_names_are_unique(self) -> None:
        names = [case["name"] for case in dgxeval.CASES]
        self.assertEqual(len(names), len(set(names)))

    def test_every_case_has_a_checker_and_prompt(self) -> None:
        for case in dgxeval.CASES:
            self.assertTrue(callable(case["check"]), case["name"])
            self.assertTrue(case["prompt"].strip(), case["name"])

    def test_arithmetic_case_accepts_only_391(self) -> None:
        case = next(c for c in dgxeval.CASES if c["name"] == "arithmetic")
        self.assertTrue(case["check"]("391"))
        self.assertFalse(case["check"]("390"))


if __name__ == "__main__":
    unittest.main()
