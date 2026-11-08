#!/usr/bin/env python3
"""Resolve image tags to digests and read their platform list.

Two callers, one implementation:

* the GitOps renderer pins every image to ``repo@sha256:...`` so a rendered
  tree is reproducible and an upstream tag move cannot silently change it;
* the engines role refuses to schedule an image that publishes no
  ``linux/arm64`` manifest, because a DGX Spark cannot run it.

The registry protocol is plain HTTP with a bearer token; ``fetch`` is
injectable so the tests never touch the network.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from typing import Any, Callable

ACCEPT = ", ".join(
    [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]
)

Fetch = Callable[[str, dict[str, str]], tuple[bytes, dict[str, str]]]


class RegistryError(Exception):
    pass


def _fetch(url: str, headers: dict[str, str], timeout: int = 20) -> tuple[bytes, dict[str, str]]:
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read(), dict(response.headers)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise RegistryError(f"{url}: HTTP {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise RegistryError(f"{url}: {exc.reason}") from exc


def parse_image(ref: str) -> tuple[str, str, str]:
    """Split an image reference into (registry, repository, tag)."""
    if "@" in ref:
        name, _digest = ref.split("@", 1)
        tag = ""
    else:
        name, tag = ref, "latest"
        head, sep, tail = name.rpartition(":")
        if sep and "/" not in tail:
            name, tag = head, tail
    parts = name.split("/")
    if len(parts) > 1 and ("." in parts[0] or ":" in parts[0] or parts[0] == "localhost"):
        registry, repository = parts[0], "/".join(parts[1:])
    else:
        registry, repository = "registry-1.docker.io", name
    if registry == "registry-1.docker.io" and "/" not in repository:
        repository = "library/" + repository
    return registry, repository, tag


def token_url(registry: str, repository: str) -> str:
    if registry == "registry-1.docker.io":
        return (
            "https://auth.docker.io/token"
            f"?service=registry.docker.io&scope=repository:{repository}:pull"
        )
    return f"https://{registry}/token?service={registry}&scope=repository:{repository}:pull"


def bearer_token(registry: str, repository: str, fetch: Fetch = _fetch) -> str | None:
    """Anonymous pull token. Public images allow this; private ones fail loudly."""
    body, _headers = fetch(token_url(registry, repository), {})
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RegistryError(f"token response for {repository} was not JSON") from exc
    return data.get("token") or data.get("access_token")


def _header(headers: dict[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return None


def manifest(image: str, fetch: Fetch = _fetch) -> tuple[dict[str, Any], str]:
    """Return (manifest document, digest) for an image reference."""
    registry, repository, tag = parse_image(image)
    # A repo@sha256: reference must be fetched *by digest*; falling back to
    # "latest" would verify a different image than the one pinned.
    reference = image.split("@", 1)[1] if "@" in image else (tag or "latest")
    headers = {"Accept": ACCEPT}
    token = bearer_token(registry, repository, fetch)
    if token:
        headers["Authorization"] = "Bearer " + token
    url = f"https://{registry}/v2/{repository}/manifests/{reference}"
    body, response_headers = fetch(url, headers)
    digest = _header(response_headers, "Docker-Content-Digest")
    if not digest:
        digest = "sha256:" + hashlib.sha256(body).hexdigest()
    try:
        document = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RegistryError(f"manifest for {image} was not JSON") from exc
    return document, digest


def platforms(document: dict[str, Any]) -> list[tuple[str, str]] | None:
    """Platforms in a multi-arch index, or None when the image is single-arch."""
    entries = document.get("manifests")
    if not isinstance(entries, list):
        return None
    found = {
        (entry.get("platform", {}).get("os"), entry.get("platform", {}).get("architecture"))
        for entry in entries
        if isinstance(entry, dict) and entry.get("platform")
    }
    return sorted(p for p in found if all(p))


def strip_tag(image: str) -> str:
    """Drop a tag or digest, keeping the registry and repository."""
    name = image.split("@", 1)[0]
    head, sep, tail = name.rpartition(":")
    if sep and "/" not in tail:
        return head
    return name


def pin(image: str, fetch: Fetch = _fetch) -> str:
    """Return ``repo@sha256:...`` for an image tag."""
    _document, digest = manifest(image, fetch)
    return f"{strip_tag(image)}@{digest}"


def supports(image: str, arch: str = "arm64", fetch: Fetch = _fetch) -> bool | None:
    """True/False when the image publishes an index; None when it is single-arch."""
    document, _digest = manifest(image, fetch)
    found = platforms(document)
    if found is None:
        return None
    return any(platform_arch == arch for _os, platform_arch in found)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", action="append", default=[], help="image reference")
    parser.add_argument("--arch", default="arm64")
    parser.add_argument("--pin", action="store_true", help="print images pinned to digests")
    args = parser.parse_args(argv)
    if not args.image:
        parser.error("pass at least one --image")

    results = []
    failed = 0
    for image in args.image:
        try:
            document, digest = manifest(image)
            found = platforms(document)
            ok = None if found is None else any(a == args.arch for _os, a in found)
            results.append(
                {
                    "image": image,
                    "digest": digest,
                    "pinned": f"{strip_tag(image)}@{digest}",
                    "platforms": found,
                    "supports_arch": ok,
                }
            )
            if args.pin:
                print(results[-1]["pinned"])
        except RegistryError as exc:
            failed += 1
            results.append({"image": image, "error": str(exc)})
    if not args.pin:
        print(json.dumps(results, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
