#!/usr/bin/env python3
"""Render the catalog into GitOps artifacts and non-Ollama engine manifests.

One implementation serves two callers:

* ``--gitops DIR`` writes an Argo CD Application plus per-engine Deployments,
  so day-2 changes can be reviewed as a diff instead of a playbook run.
* ``--engines-only FILE`` writes only the engine manifests; the ``dgx_engines``
  role copies that file to the target and applies it.

Keeping both here means the manifests applied by Ansible and the ones committed
under GitOps cannot drift.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dgxcatalog  # noqa: E402
import registry  # noqa: E402

DEFAULT_RESOURCES = {
    "requests": {"cpu": "4", "memory": "1Gi"},
    "limits": {"cpu": "10", "memory": "120Gi", "nvidia.com/gpu": "1"},
}

ENGINE_IMAGES = {
    "vllm": "vllm/vllm-openai:latest",
    "llamacpp": "ghcr.io/ggerganov/llama.cpp:server",
    "sglang": "lmsysorg/sglang:latest",
}

# Each engine's own default port, so a catalog entry can omit it.
ENGINE_PORTS = {"vllm": 8000, "llamacpp": 8080, "sglang": 30000}

# The model PVC is prefixed by engine so a volume name never collides with the
# Ollama PVCs the chart creates. `dgx_backup` selects the same prefixes.
ENGINE_PVC_PREFIX = {"vllm": "vllm", "llamacpp": "llamacpp", "sglang": "sglang"}


def _fetch_init(script: str) -> dict[str, Any]:
    return {
        "name": "fetch-weights",
        "image": "python:3.12-slim",
        "command": ["sh", "-c"],
        "args": [script],
        "volumeMounts": [{"name": "models", "mountPath": "/models"}],
        "resources": {"requests": {"cpu": "2", "memory": "2Gi"}},
    }


def chart_model(name: str, entry: dict[str, Any], enabled: bool) -> dict[str, Any]:
    return {
        "enabled": enabled,
        "image": "ollama/ollama:latest",
        "ollamaPull": entry["tag"],
        "displayName": entry.get("display_name", name),
        "port": int(entry.get("port", 11434)),
        "numCtx": str(entry["default_ctx"]),
        "numParallel": str(entry.get("default_parallel", 1)),
        "resources": DEFAULT_RESOURCES,
        "persistence": {
            "storageClass": "longhorn-models",
            "size": entry["size"],
        },
    }


def engine_manifest(
    name: str,
    entry: dict[str, Any],
    namespace: str,
    offline: bool = False,
) -> list[dict[str, Any]]:
    engine = entry["engine"]
    image = ENGINE_IMAGES.get(engine)
    if image is None:
        raise SystemExit(f"no image mapped for engine {engine}")
    port = int(entry.get("port", ENGINE_PORTS.get(engine, 8000)))
    pvc = f"{ENGINE_PVC_PREFIX.get(engine, engine)}-{name}"
    labels = {"app": name, "dgx10/model": name, "dgx10/engine": engine}

    if engine == "vllm":
        args = [
            "--model", "/models",
            "--served-model-name", name,
            "--port", str(port),
            "--max-model-len", str(entry["default_ctx"]),
            "--gpu-memory-utilization", "0.40",
            "--trust-remote-code",
        ]
        command: list[str] = []
    elif engine == "llamacpp":
        # --alias makes /v1/models report the catalog name rather than the
        # GGUF filename, so the probe and the gateway address it by name.
        args = ["-m", "/models/model.gguf", "--host", "0.0.0.0",
                "--port", str(port), "-c", str(entry["default_ctx"]),
                "--alias", name]
        command = []
    else:
        args = ["--model-path", "/models", "--served-model-name", name,
                "--port", str(port), "--context-length",
                str(entry["default_ctx"])]
        command = ["python3", "-m", "sglang.launch_server"]

    if offline:
        # The weights are expected to be on the PVC already (the offline bundle
        # carries it); fetching here would fail on an air-gapped box.
        init_containers: list[dict[str, Any]] = []
    elif engine == "llamacpp":
        weights_file = entry.get("weights_file", "model.gguf")
        init_containers = [_fetch_init(
            "pip install -q huggingface_hub && "
            "python3 -c \"from huggingface_hub import hf_hub_download; "
            f"hf_hub_download('{entry['tag']}', '{weights_file}', local_dir='/models')\" && "
            f"mv '/models/{weights_file}' /models/model.gguf"
        )]
    else:
        init_containers = [_fetch_init(
            "pip install -q huggingface_hub && "
            "python3 -c \"from huggingface_hub import snapshot_download; "
            f"snapshot_download('{entry['tag']}', local_dir='/models')\""
        )]

    deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": name, "namespace": namespace, "labels": labels},
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": labels},
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "nodeSelector": {"kubernetes.io/arch": "arm64"},
                    "initContainers": init_containers,
                    "containers": [{
                        "name": engine,
                        "image": image,
                        "command": command or None,
                        "args": args,
                        "ports": [{"name": "http", "containerPort": port}],
                        "resources": {
                            "requests": {"cpu": "4", "memory": "8Gi", "nvidia.com/gpu": "1"},
                            "limits": {"cpu": "10", "memory": "110Gi", "nvidia.com/gpu": "1"},
                        },
                        "volumeMounts": [{"name": "models", "mountPath": "/models"}],
                        "readinessProbe": {
                            "httpGet": {"path": "/health", "port": "http"},
                            "initialDelaySeconds": 30,
                            "periodSeconds": 10,
                            "failureThreshold": 30,
                        },
                    }],
                    "volumes": [{
                        "name": "models",
                        "persistentVolumeClaim": {"claimName": pvc},
                    }],
                },
            },
        },
    }
    service = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": name, "namespace": namespace, "labels": labels},
        "spec": {
            "selector": labels,
            "ports": [{
                "name": "http",
                "port": port,
                "targetPort": "http",
            }],
        },
    }
    pvc_doc = {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": {
            "name": pvc,
            "namespace": namespace,
            "annotations": {"helm.sh/resource-policy": "keep"},
        },
        "spec": {
            "accessModes": ["ReadWriteOnce"],
            "storageClassName": "longhorn-models",
            "resources": {"requests": {"storage": entry["size"]}},
        },
    }
    return [pvc_doc, deployment, service]


def render_app(
    models: dict[str, Any],
    namespace: str,
    repo_url: str,
    revision: str,
) -> dict[str, Any]:
    return {
        "apiVersion": "argoproj.io/v1alpha1",
        "kind": "Application",
        "metadata": {"name": "llm-serving", "namespace": "argocd"},
        "spec": {
            "project": "default",
            "source": {
                "repoURL": repo_url,
                "targetRevision": revision,
                "path": "charts/llm-serving",
                "helm": {"valuesObject": {"models": models}},
            },
            "destination": {
                "server": "https://kubernetes.default.svc",
                "namespace": namespace,
            },
            "syncPolicy": {
                "automated": {"prune": True, "selfHeal": True},
                "syncOptions": ["CreateNamespace=true"],
            },
        },
    }


def _pinned(image: str, cache: dict[str, str]) -> str:
    if image not in cache:
        try:
            cache[image] = registry.pin(image)
        except registry.RegistryError as exc:
            raise SystemExit(f"cannot pin {image}: {exc}") from exc
    return cache[image]


def pin_documents(documents: list[dict[str, Any]]) -> None:
    """Rewrite every image reference to repo@sha256, in place.

    A rendered tree is only reproducible if the tag's digest is recorded. This
    walks the whole document, including the Helm valuesObject, so no image is
    left floating on a mutable tag.
    """
    cache: dict[str, str] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            image = node.get("image")
            if isinstance(image, str) and "@" not in image:
                node["image"] = _pinned(image, cache)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for document in documents:
        walk(document)


def image_refs(documents: list[dict[str, Any]]) -> list[str]:
    """Every ``image`` value in the rendered tree, de-duplicated and sorted."""
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            image = node.get("image")
            if isinstance(image, str):
                found.add(image)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for document in documents:
        walk(document)
    return sorted(found)


def check_arch(
    images: list[str],
    arch: str,
    fetch: registry.Fetch | None = None,
) -> dict[str, list[str]]:
    """Sort images into unsupported and unverifiable.

    A single-arch manifest (``supports`` returns None) is not evidence of a
    mismatch: the image may still be arm64. Only a multi-arch index that lists
    other architectures is a definite failure, so an air-gapped controller that
    cannot reach the registry never blocks an otherwise valid render.
    """
    kwargs = {"fetch": fetch} if fetch is not None else {}
    unsupported: list[str] = []
    unknown: list[str] = []
    for image in images:
        try:
            ok = registry.supports(image, arch, **kwargs)
        except registry.RegistryError as exc:
            unknown.append(f"{image}: {exc}")
            continue
        if ok is False:
            unsupported.append(image)
        elif ok is None:
            unknown.append(f"{image}: single-arch manifest, architecture not declared")
    return {"unsupported": unsupported, "unknown": unknown}


def build(args: argparse.Namespace) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    catalog = dgxcatalog.load_catalog()
    if args.profile:
        profile = dgxcatalog.resolve_profile(args.profile, catalog)
        names = list(profile["base"]) + list(profile["extras"])
    elif args.model:
        names = list(args.model)
    else:
        raise SystemExit("pass --profile or --model")

    plan = dgxcatalog.build_plan(names, catalog)
    if plan["verdict"] == "FAIL":
        raise SystemExit("refusing to render a set that does not fit: " + "; ".join(plan["reasons"]))

    models: dict[str, Any] = {}
    for base in catalog.get("base_models", []):
        entry = catalog["models"][base]
        models[base] = chart_model(base, entry, base in names)
    engines: list[dict[str, Any]] = []
    for name in names:
        entry = catalog["models"][name]
        if name in catalog.get("base_models", []):
            continue
        if entry["engine"] == "ollama":
            models[name] = chart_model(name, entry, True)
        else:
            engines.extend(engine_manifest(
                name, entry, args.namespace,
                offline=getattr(args, "offline", False),
            ))
    app = render_app(models, args.namespace, args.repo_url, args.revision)
    if getattr(args, "pin_digests", False):
        pin_documents([app] + engines)
    return app, engines, names


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--profile")
    p.add_argument("--model", action="append", default=[])
    p.add_argument("--namespace", default="llm-serving")
    p.add_argument("--repo-url", default="https://github.com/blik616287/dgx_spark_kubeadm_deployment")
    p.add_argument("--revision", default="4a0c97129da8a61f65ff9009bd63689fc12b70a1")
    p.add_argument("--gitops", help="write an Argo CD tree here")
    p.add_argument("--engines-only", help="write only engine manifests to this file")
    p.add_argument("--pin-digests", action="store_true",
                   help="resolve every image to repo@sha256 (needs registry access)")
    p.add_argument("--offline", action="store_true",
                   help="omit the weight-fetch init container (weights are on the PVC)")
    p.add_argument("--check-arch", default="",
                   help="verify every image publishes this architecture (e.g. arm64)")
    args = p.parse_args(argv)

    app, engines, names = build(args)

    if args.check_arch:
        verdict = check_arch(image_refs([app] + engines), args.check_arch)
        for note in verdict["unknown"]:
            print(f"warning: cannot verify {note}", file=sys.stderr)
        if verdict["unsupported"]:
            print(
                "error: no linux/" + args.check_arch + " manifest for: "
                + ", ".join(verdict["unsupported"]),
                file=sys.stderr,
            )
            return 1
    if args.gitops:
        root = Path(args.gitops)
        (root / "engines").mkdir(parents=True, exist_ok=True)
        (root / "app.yaml").write_text(yaml.safe_dump(app, sort_keys=False))
        for doc in engines:
            path = root / "engines" / f'{doc["metadata"]["name"]}.yaml'
            path.write_text(yaml.safe_dump(doc, sort_keys=False))
        (root / "README.md").write_text(
            "# GitOps tree\n\n"
            f"Models: {', '.join(names)}\n\n"
            "Apply `app.yaml` with Argo CD; it renders the upstream chart with the\n"
            "model set embedded as `helm.valuesObject`. Engine manifests in\n"
            "`engines/` are applied separately because the chart serves Ollama only.\n"
        )
        print(f"wrote {root}/app.yaml and {len(engines)} engine document(s)")
    if args.engines_only:
        Path(args.engines_only).write_text(
            yaml.safe_dump_all(engines, sort_keys=False) if engines else ""
        )
        print(f"wrote {len(engines)} engine document(s) to {args.engines_only}")
    if not args.gitops and not args.engines_only:
        print(yaml.safe_dump(app, sort_keys=False), end="")
        if engines:
            print("---")
            print(yaml.safe_dump_all(engines, sort_keys=False), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
