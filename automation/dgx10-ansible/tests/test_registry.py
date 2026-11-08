"""Registry helper tests. Run: python -m unittest discover -s tests

The network is never touched: every test injects a fake ``fetch``.
"""

from __future__ import annotations

import base64
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import registry  # noqa: E402

INDEX = {
    "schemaVersion": 2,
    "mediaType": "application/vnd.oci.image.index.v1+json",
    "manifests": [
        {"platform": {"os": "linux", "architecture": "amd64"}},
        {"platform": {"os": "linux", "architecture": "arm64"}},
    ],
}
AMD_ONLY = {
    "schemaVersion": 2,
    "manifests": [{"platform": {"os": "linux", "architecture": "amd64"}}],
}
SINGLE = {"schemaVersion": 2, "config": {}, "layers": []}


def fake_fetch(document, digest="sha256:" + "a" * 64, seen=None):
    def fetch(url, headers, timeout=20):
        if seen is not None:
            seen.append((url, headers))
        if "/token" in url:
            return json.dumps({"token": "anon-token"}).encode(), {}
        return json.dumps(document).encode(), {"Docker-Content-Digest": digest}

    return fetch


class ParseTests(unittest.TestCase):
    def test_docker_hub_short_name_gets_library(self) -> None:
        self.assertEqual(
            registry.parse_image("busybox:1.36"),
            ("registry-1.docker.io", "library/busybox", "1.36"),
        )

    def test_default_tag_is_latest(self) -> None:
        self.assertEqual(
            registry.parse_image("ghcr.io/ggerganov/llama.cpp"),
            ("ghcr.io", "ggerganov/llama.cpp", "latest"),
        )

    def test_registry_with_port_is_not_a_tag(self) -> None:
        self.assertEqual(
            registry.parse_image("localhost:5000/team/model:v1"),
            ("localhost:5000", "team/model", "v1"),
        )

    def test_digest_reference_has_no_tag(self) -> None:
        registry_name, repository, tag = registry.parse_image("ghcr.io/a/b@sha256:" + "b" * 64)
        self.assertEqual((registry_name, repository, tag), ("ghcr.io", "a/b", ""))

    def test_strip_tag_keeps_the_registry_port(self) -> None:
        self.assertEqual(registry.strip_tag("localhost:5000/team/model:v1"), "localhost:5000/team/model")


class TokenTests(unittest.TestCase):
    def test_docker_hub_uses_auth_endpoint(self) -> None:
        self.assertIn("auth.docker.io", registry.token_url("registry-1.docker.io", "library/busybox"))

    def test_other_registries_use_their_own_token_endpoint(self) -> None:
        self.assertEqual(
            registry.token_url("ghcr.io", "ggerganov/llama.cpp"),
            "https://ghcr.io/token?service=ghcr.io&scope=repository:ggerganov/llama.cpp:pull",
        )

    def test_bearer_token_is_returned(self) -> None:
        self.assertEqual(
            registry.bearer_token("ghcr.io", "a/b", fake_fetch(INDEX)), "anon-token"
        )


class ManifestTests(unittest.TestCase):
    def test_digest_comes_from_the_header(self) -> None:
        _doc, digest = registry.manifest("busybox:1.36", fake_fetch(INDEX, "sha256:" + "c" * 64))
        self.assertEqual(digest, "sha256:" + "c" * 64)

    def test_digest_is_computed_when_the_header_is_missing(self) -> None:
        def fetch(url, headers, timeout=20):
            if "/token" in url:
                return b'{"token": "t"}', {}
            return json.dumps(INDEX).encode(), {}

        _doc, digest = registry.manifest("busybox:1.36", fetch)
        self.assertTrue(digest.startswith("sha256:"))
        self.assertEqual(len(digest), 7 + 64)

    def test_digest_reference_is_fetched_by_digest(self) -> None:
        seen: list = []
        digest = "sha256:" + "f" * 64
        registry.manifest("ghcr.io/a/b@" + digest, fake_fetch(INDEX, seen=seen))
        manifest_url, _headers = seen[-1]
        self.assertTrue(manifest_url.endswith("/manifests/" + digest), manifest_url)

    def test_request_asks_for_both_oci_and_docker_manifests(self) -> None:
        seen: list = []
        registry.manifest("busybox:1.36", fake_fetch(INDEX, seen=seen))
        manifest_url, headers = seen[-1]
        self.assertIn("/v2/library/busybox/manifests/1.36", manifest_url)
        self.assertEqual(headers["Authorization"], "Bearer anon-token")
        self.assertIn("application/vnd.oci.image.index.v1+json", headers["Accept"])
        self.assertIn("application/vnd.docker.distribution.manifest.list.v2+json", headers["Accept"])


class PlatformTests(unittest.TestCase):
    def test_index_platforms_are_sorted(self) -> None:
        self.assertEqual(
            registry.platforms(INDEX),
            [("linux", "amd64"), ("linux", "arm64")],
        )

    def test_single_arch_manifest_returns_none(self) -> None:
        self.assertIsNone(registry.platforms(SINGLE))

    def test_supports_arm64_true(self) -> None:
        self.assertTrue(registry.supports("busybox:1.36", "arm64", fake_fetch(INDEX)))

    def test_supports_arm64_false(self) -> None:
        self.assertFalse(registry.supports("busybox:1.36", "arm64", fake_fetch(AMD_ONLY)))

    def test_supports_is_unknown_for_single_arch(self) -> None:
        self.assertIsNone(registry.supports("busybox:1.36", "arm64", fake_fetch(SINGLE)))

    def test_pin_returns_repo_at_digest(self) -> None:
        self.assertEqual(
            registry.pin("busybox:1.36", fake_fetch(INDEX, "sha256:" + "d" * 64)),
            "busybox@sha256:" + "d" * 64,
        )


class ErrorTests(unittest.TestCase):
    def test_registry_error_is_raised_for_bad_json(self) -> None:
        def fetch(url, headers, timeout=20):
            if "/token" in url:
                return b'{"token": "t"}', {}
            return b"not json", {}

        with self.assertRaises(registry.RegistryError):
            registry.manifest("busybox:1.36", fetch)


if __name__ == "__main__":
    unittest.main()
