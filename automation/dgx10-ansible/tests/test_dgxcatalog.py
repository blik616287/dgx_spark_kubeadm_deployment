"""Planner tests. Run: python -m unittest discover -s tests"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import dgxcatalog  # noqa: E402


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = dgxcatalog.load_catalog()

    def test_catalog_validates(self) -> None:
        self.assertGreaterEqual(len(self.catalog["models"]), 10)
        self.assertIn("minimal", self.catalog["profiles"])

    def test_every_profile_fits(self) -> None:
        for name, profile in self.catalog["profiles"].items():
            models = list(profile.get("base", [])) + list(profile.get("extras", []))
            plan = dgxcatalog.build_plan(models, self.catalog)
            self.assertNotEqual(plan["verdict"], "FAIL", f"{name}: {plan['reasons']}")

    def test_fit_math(self) -> None:
        entry = self.catalog["models"]["qwen3-8b"]
        fit = dgxcatalog.model_fit(entry)
        self.assertAlmostEqual(fit["kv_gib"], round(0.06 * 32.768, 2), places=2)
        self.assertAlmostEqual(
            fit["total_gib"],
            entry["weights_gib"] + fit["kv_gib"] + entry["overhead_gib"],
            places=2,
        )

    def test_parallel_requests_multiply_kv(self) -> None:
        entry = self.catalog["models"]["qwen3-8b"]
        one = dgxcatalog.model_fit(entry, parallel=1)
        two = dgxcatalog.model_fit(entry, parallel=2)
        self.assertAlmostEqual(two["kv_gib"], round(0.06 * 32.768 * 2, 2), places=2)

    def test_impossible_set_fails(self) -> None:
        plan = dgxcatalog.build_plan(
            ["gpt-oss-120b", "llama3.3-70b", "qwen3-32b"], self.catalog
        )
        self.assertEqual(plan["verdict"], "FAIL")
        self.assertGreater(plan["used_gib"], plan["budget_gib"])

    def test_slice_budget_fails(self) -> None:
        names = ["qwen3-8b", "qwen3-14b", "qwen3-32b", "gemma3-27b", "devstral-24b", "phi4-14b"]
        plan = dgxcatalog.build_plan(names, self.catalog)
        self.assertEqual(plan["verdict"], "FAIL")
        self.assertGreater(plan["slices_used"], plan["slices_max"])

    def test_unknown_model_fails(self) -> None:
        plan = dgxcatalog.build_plan(["not-a-model"], self.catalog)
        self.assertEqual(plan["verdict"], "FAIL")
        self.assertEqual(plan["unknown"], ["not-a-model"])

    def test_resolution_splits_chart_and_engine_models(self) -> None:
        profile = dgxcatalog.resolve_profile("rag", self.catalog)
        names = profile["base"] + profile["extras"]
        result = dgxcatalog.build_resolution(names, self.catalog, "rag")
        extra_names = [m["name"] for m in result["extra_models"]]
        engine_names = [m["name"] for m in result["engine_models"]]
        self.assertIn("qwen3-8b", extra_names)
        self.assertIn("qwen3-embedding-0.6b", extra_names)
        self.assertEqual(engine_names, ["bge-reranker-v2-m3"])

    def test_resolution_marks_base_models(self) -> None:
        result = dgxcatalog.build_resolution(
            ["qwen3-coder-next", "qwen3-14b"], self.catalog, "coding"
        )
        self.assertEqual(result["models_enabled"], ["qwen3-coder-next"])
        self.assertEqual([m["name"] for m in result["extra_models"]], ["qwen3-14b"])

    def test_render_table_mentions_verdict(self) -> None:
        plan = dgxcatalog.build_plan(["qwen3-8b"], self.catalog)
        table = dgxcatalog.render_table(plan)
        self.assertIn("PASS", table)
        self.assertIn("qwen3-8b", table)

    def test_cli_plan_exit_code(self) -> None:
        self.assertEqual(
            dgxcatalog.main(["--catalog", str(ROOT / "catalog" / "models.yaml"),
                             "plan", "--profile", "minimal"]),
            0,
        )


if __name__ == "__main__":
    unittest.main()
