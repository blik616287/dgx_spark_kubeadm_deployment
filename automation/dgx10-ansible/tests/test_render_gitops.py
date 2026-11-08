"""GitOps/engine renderer tests. Run: python -m unittest discover -s tests"""

from __future__ import annotations

import sys
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import render_gitops  # noqa: E402


def args(profile: str | None = None, model: list[str] | None = None, **extra) -> Namespace:
    return Namespace(
        profile=profile,
        model=model or [],
        namespace="llm-serving",
        repo_url="https://example.invalid/repo",
        revision="deadbeef",
        **extra,
    )


class RenderTests(unittest.TestCase):
    def test_profile_renders_engine_manifest_for_vllm(self) -> None:
        app, engines, names = render_gitops.build(args(profile="rag"))
        self.assertIn("bge-reranker-v2-m3", names)
        kinds = [doc["kind"] for doc in engines]
        self.assertIn("Deployment", kinds)
        self.assertIn("PersistentVolumeClaim", kinds)
        deployment = next(d for d in engines if d["kind"] == "Deployment")
        self.assertEqual(deployment["spec"]["template"]["spec"]["containers"][0]["name"], "vllm")

    def test_all_ollama_selection_has_no_engines(self) -> None:
        _, engines, names = render_gitops.build(args(profile="coding"))
        self.assertEqual(engines, [])
        self.assertEqual(names, ["qwen3-coder-next", "qwen3-14b"])

    def test_app_embeds_the_chart_values(self) -> None:
        app, _, _ = render_gitops.build(args(profile="minimal"))
        values = app["spec"]["source"]["helm"]["valuesObject"]["models"]
        self.assertTrue(values["qwen3-coder-next"]["enabled"])
        self.assertFalse(values["deepseek-r1-distill-32b"]["enabled"])

    def test_impossible_set_is_refused(self) -> None:
        with self.assertRaises(SystemExit):
            render_gitops.build(
                args(model=["gpt-oss-120b", "qwen3-coder-next", "deepseek-r1-distill-32b"])
            )

    def test_llamacpp_downloads_only_the_gguf(self) -> None:
        _, engines, _ = render_gitops.build(args(model=["qwen3-8b-gguf"]))
        deployment = next(d for d in engines if d["kind"] == "Deployment")
        pod = deployment["spec"]["template"]["spec"]
        init = pod["initContainers"][0]
        self.assertIn("hf_hub_download", init["args"][0])
        self.assertIn("Qwen3-8B-Q4_K_M.gguf", init["args"][0])
        container = pod["containers"][0]
        self.assertEqual(container["name"], "llamacpp")
        self.assertEqual(container["args"][container["args"].index("--alias") + 1], "qwen3-8b-gguf")
        pvc = next(d for d in engines if d["kind"] == "PersistentVolumeClaim")
        self.assertEqual(pvc["metadata"]["name"], "llamacpp-qwen3-8b-gguf")

    def test_sglang_keeps_its_own_port(self) -> None:
        _, engines, _ = render_gitops.build(args(model=["qwen3-8b-sglang"]))
        deployment = next(d for d in engines if d["kind"] == "Deployment")
        container = deployment["spec"]["template"]["spec"]["containers"][0]
        self.assertEqual(
            container["args"][container["args"].index("--port") + 1], "30000"
        )
        service = next(d for d in engines if d["kind"] == "Service")
        self.assertEqual(service["spec"]["ports"][0]["port"], 30000)

    def test_offline_omits_the_fetch_container(self) -> None:
        _, engines, _ = render_gitops.build(
            args(model=["qwen3-8b-gguf"], offline=True)
        )
        deployment = next(d for d in engines if d["kind"] == "Deployment")
        self.assertEqual(deployment["spec"]["template"]["spec"]["initContainers"], [])

    def test_pin_digests_rewrites_every_image(self) -> None:
        def fake_pin(image: str) -> str:
            return image.split(":")[0] + "@sha256:" + "e" * 64

        with mock.patch.object(render_gitops.registry, "pin", side_effect=fake_pin):
            app, engines, _ = render_gitops.build(
                args(profile="rag", pin_digests=True)
            )

        def images(node):
            if isinstance(node, dict):
                if isinstance(node.get("image"), str):
                    yield node["image"]
                for value in node.values():
                    yield from images(value)
            elif isinstance(node, list):
                for item in node:
                    yield from images(item)

        found = list(images([app] + engines))
        self.assertTrue(found)
        self.assertTrue(all("@" in image for image in found), found)


class ArchCheckTests(unittest.TestCase):
    def test_image_refs_finds_nested_images_once(self) -> None:
        documents = [
            {"spec": {"containers": [{"image": "b:1"}, {"image": "a:1"}]}},
            {"spec": {"initContainers": [{"image": "a:1"}]}},
        ]
        self.assertEqual(render_gitops.image_refs(documents), ["a:1", "b:1"])

    def test_image_refs_ignores_non_string_images(self) -> None:
        self.assertEqual(render_gitops.image_refs([{"image": None}]), [])

    def test_arm64_image_is_neither_unsupported_nor_unknown(self) -> None:
        with mock.patch.object(render_gitops.registry, "supports", return_value=True):
            verdict = render_gitops.check_arch(["a:1"], "arm64")
        self.assertEqual(verdict, {"unsupported": [], "unknown": []})

    def test_amd64_only_image_is_unsupported(self) -> None:
        with mock.patch.object(render_gitops.registry, "supports", return_value=False):
            verdict = render_gitops.check_arch(["a:1"], "arm64")
        self.assertEqual(verdict["unsupported"], ["a:1"])
        self.assertEqual(verdict["unknown"], [])

    def test_single_arch_manifest_is_unknown_not_a_failure(self) -> None:
        # `supports` returns None for a single-arch manifest: the image may
        # still be arm64, so it must not block the render.
        with mock.patch.object(render_gitops.registry, "supports", return_value=None):
            verdict = render_gitops.check_arch(["a:1"], "arm64")
        self.assertEqual(verdict["unsupported"], [])
        self.assertEqual(len(verdict["unknown"]), 1)
        self.assertIn("single-arch", verdict["unknown"][0])

    def test_unreachable_registry_is_unknown(self) -> None:
        with mock.patch.object(
            render_gitops.registry,
            "supports",
            side_effect=render_gitops.registry.RegistryError("boom"),
        ):
            verdict = render_gitops.check_arch(["a:1"], "arm64")
        self.assertEqual(verdict["unsupported"], [])
        self.assertIn("boom", verdict["unknown"][0])

    def test_check_arch_queries_every_rendered_image(self) -> None:
        app, engines, _ = render_gitops.build(args(profile="rag"))
        expected = render_gitops.image_refs([app] + engines)
        self.assertTrue(expected)
        with mock.patch.object(
            render_gitops.registry, "supports", return_value=True
        ) as supports:
            render_gitops.check_arch(expected, "arm64")
        self.assertEqual(supports.call_count, len(expected))


if __name__ == "__main__":
    unittest.main()
