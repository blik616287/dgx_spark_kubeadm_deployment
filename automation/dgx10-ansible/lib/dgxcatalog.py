#!/usr/bin/env python3
"""Catalog, profile resolution and fit planning for the DGX Spark model set.

The chart's ``values.yaml`` describes how to *run* a model. This module
describes whether it *fits*: weights, KV cache at the chosen context, runtime
overhead, and the time-sliced GPU budget. Nothing here talks to a cluster, so
``plan`` is safe to run on a laptop and before any download.

Everything is an estimate except the catalog's own numbers. Weights come from
the published quant, KV cache from the model's reported KV geometry times the
context and parallel-request count, and overhead is a fixed allowance. The
point is to fail an impossible set in seconds instead of discovering it when a
pod is Pending or OOMKilled an hour into a pull.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - the caller turns this into a message
    yaml = None


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "catalog" / "models.yaml"
PROFILES_PATH = ROOT / "catalog" / "profiles.yaml"

ENGINES = ("ollama", "vllm", "llamacpp", "sglang")
CAPABILITIES = ("chat", "tools", "vision", "embedding", "rerank")

# Fields every model entry must carry. Optional fields have defaults below.
REQUIRED_MODEL_FIELDS = (
    "tag",
    "engine",
    "params_b",
    "quant",
    "weights_gib",
    "kv_gib_per_1k",
    "default_ctx",
    "max_ctx",
    "capabilities",
    "license",
    "size",
)


class CatalogError(Exception):
    """A catalog or profile the planner cannot trust."""


def _require_yaml() -> None:
    if yaml is None:  # pragma: no cover
        raise CatalogError(
            "PyYAML is required. Run this with the interpreter that runs Ansible "
            "(ansible_playbook_python), or `pip install pyyaml`."
        )


def _read_yaml(path: Path) -> dict[str, Any]:
    _require_yaml()
    if not path.exists():
        raise CatalogError(f"{path} does not exist")
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:  # pragma: no cover - malformed input
        raise CatalogError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise CatalogError(f"{path} must contain a mapping")
    return data


def load_catalog(path: Path | None = None) -> dict[str, Any]:
    """Load and validate the model catalog and its profiles."""
    catalog = _read_yaml(path or CATALOG_PATH)
    if catalog.get("version") != 1:
        raise CatalogError("catalog version must be 1")

    budget = catalog.get("budget")
    if not isinstance(budget, dict):
        raise CatalogError("catalog.budget must be a mapping")
    for key in ("unified_memory_gib", "host_reserve_gib", "gpu_time_slices"):
        if key not in budget:
            raise CatalogError(f"catalog.budget.{key} is required")

    models = catalog.get("models")
    if not isinstance(models, dict) or not models:
        raise CatalogError("catalog.models must be a non-empty mapping")

    for name, entry in models.items():
        if not isinstance(entry, dict):
            raise CatalogError(f"model {name} must be a mapping")
        missing = [f for f in REQUIRED_MODEL_FIELDS if f not in entry]
        if missing:
            raise CatalogError(f"model {name} is missing: {', '.join(missing)}")
        if entry["engine"] not in ENGINES:
            raise CatalogError(f"model {name}: engine must be one of {ENGINES}")
        if entry["weights_gib"] <= 0:
            raise CatalogError(f"model {name}: weights_gib must be positive")
        if entry["kv_gib_per_1k"] < 0:
            raise CatalogError(f"model {name}: kv_gib_per_1k cannot be negative")
        if entry["default_ctx"] > entry["max_ctx"]:
            raise CatalogError(f"model {name}: default_ctx exceeds max_ctx")
        unknown = [c for c in entry["capabilities"] if c not in CAPABILITIES]
        if unknown:
            raise CatalogError(f"model {name}: unknown capabilities {unknown}")
        entry.setdefault("default_parallel", 1)
        entry.setdefault("overhead_gib", budget.get("per_model_overhead_gib", 1.5))
        entry.setdefault("namespace", "llm-serving")
        entry.setdefault("port", 11434 if entry["engine"] == "ollama" else 8000)
        entry.setdefault("source", "ollama" if entry["engine"] == "ollama" else "huggingface")

    bases = catalog.get("base_models", [])
    if not isinstance(bases, list):
        raise CatalogError("catalog.base_models must be a list")
    for name in bases:
        if name not in models:
            raise CatalogError(f"base model {name} is not in catalog.models")

    profiles = _read_yaml(
        (path.with_name("profiles.yaml") if path is not None else PROFILES_PATH)
    )
    if profiles.get("version") != 1:
        raise CatalogError("profiles version must be 1")
    profile_map = profiles.get("profiles")
    if not isinstance(profile_map, dict) or not profile_map:
        raise CatalogError("profiles must be a non-empty mapping")
    for pname, profile in profile_map.items():
        if not isinstance(profile, dict):
            raise CatalogError(f"profile {pname} must be a mapping")
        base = profile.get("base", [])
        extras = profile.get("extras", [])
        if not isinstance(base, list) or not isinstance(extras, list):
            raise CatalogError(f"profile {pname}: base and extras must be lists")
        for name in base + extras:
            if name not in models:
                raise CatalogError(f"profile {pname} references unknown model {name}")
        if len(set(base + extras)) != len(base) + len(extras):
            raise CatalogError(f"profile {pname} lists a model twice")
        for name in base:
            if name not in bases:
                raise CatalogError(
                    f"profile {pname}: {name} is not a base model; put it in extras"
                )
        profile.setdefault("description", "")
        profile.setdefault("gateway", True)
        profile.setdefault("bundle", False)
    catalog["profiles"] = profile_map
    return catalog


def model_fit(
    entry: dict[str, Any],
    ctx: int | None = None,
    parallel: int | None = None,
) -> dict[str, Any]:
    """Return the memory line for one model at the requested context."""
    ctx = int(ctx or entry["default_ctx"])
    parallel = int(parallel or entry.get("default_parallel", 1))
    kv_gib = entry["kv_gib_per_1k"] * (ctx / 1000.0) * parallel
    weights_gib = float(entry["weights_gib"])
    overhead_gib = float(entry.get("overhead_gib", 1.5))
    total_gib = weights_gib + kv_gib + overhead_gib
    return {
        "ctx": ctx,
        "parallel": parallel,
        "weights_gib": round(weights_gib, 2),
        "kv_gib": round(kv_gib, 2),
        "overhead_gib": round(overhead_gib, 2),
        "total_gib": round(total_gib, 2),
        "slices": 1,
    }


def build_plan(names: list[str], catalog: dict[str, Any]) -> dict[str, Any]:
    """Fit a whole model set against unified memory and the slice count."""
    budget = catalog["budget"]
    usable = float(budget["unified_memory_gib"]) - float(budget["host_reserve_gib"])
    max_slices = int(budget["gpu_time_slices"])

    rows: list[dict[str, Any]] = []
    unknown: list[str] = []
    for name in names:
        entry = catalog["models"].get(name)
        if entry is None:
            unknown.append(name)
            continue
        row = model_fit(entry)
        row.update(
            name=name,
            engine=entry["engine"],
            capabilities=list(entry["capabilities"]),
            verdict="FAIL" if row["total_gib"] > usable else "PASS",
        )
        rows.append(row)

    used = round(sum(r["total_gib"] for r in rows), 2)
    headroom = round(usable - used, 2)
    slices_used = sum(r["slices"] for r in rows)

    verdict = "PASS"
    reasons: list[str] = []
    if unknown:
        verdict = "FAIL"
        reasons.append(f"unknown model(s): {', '.join(unknown)}")
    if used > usable:
        verdict = "FAIL"
        reasons.append(f"{used} GiB requested exceeds the {usable} GiB budget")
    if slices_used > max_slices:
        verdict = "FAIL"
        reasons.append(f"{slices_used} GPU slices requested, {max_slices} available")
    if verdict == "PASS" and (used > usable * 0.9 or any(r["verdict"] == "FAIL" for r in rows)):
        verdict = "WARN"
        if used > usable * 0.9:
            reasons.append(f"less than 10% headroom ({headroom} GiB left)")

    return {
        "verdict": verdict,
        "reasons": reasons,
        "budget_gib": round(usable, 2),
        "used_gib": used,
        "headroom_gib": headroom,
        "slices_used": slices_used,
        "slices_max": max_slices,
        "models": rows,
        "unknown": unknown,
    }


def render_table(plan: dict[str, Any]) -> str:
    """A fixed-width table for terminals and debug output."""
    headers = ("MODEL", "ENGINE", "CTX", "PAR", "WEIGHTS", "KV", "TOTAL", "VERDICT")
    rows = [
        (
            r["name"],
            r["engine"],
            str(r["ctx"]),
            str(r["parallel"]),
            f'{r["weights_gib"]:.1f}',
            f'{r["kv_gib"]:.1f}',
            f'{r["total_gib"]:.1f}',
            r["verdict"],
        )
        for r in plan["models"]
    ]
    widths = [
        max(len(headers[i]), *(len(row[i]) for row in rows)) if rows else len(headers[i])
        for i in range(len(headers))
    ]
    lines = [
        "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)),
        "  ".join("-" * widths[i] for i in range(len(headers))),
    ]
    for row in rows:
        lines.append("  ".join(row[i].ljust(widths[i]) for i in range(len(headers))))
    lines.append("")
    lines.append(
        f'{plan["verdict"]}: {plan["used_gib"]} / {plan["budget_gib"]} GiB, '
        f'{plan["slices_used"]} / {plan["slices_max"]} GPU slices, '
        f'{plan["headroom_gib"]} GiB headroom'
    )
    for reason in plan["reasons"]:
        lines.append(f"  - {reason}")
    return "\n".join(lines)


def resolve_profile(name: str, catalog: dict[str, Any]) -> dict[str, Any]:
    profile = catalog["profiles"].get(name)
    if profile is None:
        known = ", ".join(sorted(catalog["profiles"]))
        raise CatalogError(f"unknown profile {name!r}; known: {known}")
    return {"name": name, **profile}


def chart_entry(name: str, entry: dict[str, Any]) -> dict[str, Any]:
    """The subset of a catalog entry the llm-serving chart consumes."""
    return {
        "name": name,
        "enabled": True,
        "source": "ollama",
        "tag": entry["tag"],
        "size": entry["size"],
        "numCtx": str(entry["default_ctx"]),
        "numParallel": str(entry.get("default_parallel", 1)),
        "displayName": entry.get("display_name", name),
    }


def engine_entry(name: str, entry: dict[str, Any]) -> dict[str, Any]:
    """The shape dgx_engines needs for a non-Ollama runtime."""
    return {
        "name": name,
        "engine": entry["engine"],
        "tag": entry["tag"],
        "source": entry.get("source", "huggingface"),
        "namespace": entry.get("namespace", "llm-serving"),
        "port": int(entry.get("port", 8000)),
        "size": entry["size"],
        "ctx": int(entry["default_ctx"]),
        "parallel": int(entry.get("default_parallel", 1)),
        "capabilities": list(entry["capabilities"]),
    }


def build_resolution(names: list[str], catalog: dict[str, Any], profile: str | None) -> dict[str, Any]:
    plan = build_plan(names, catalog)
    base = set(catalog.get("base_models", []))
    extras = [
        chart_entry(n, catalog["models"][n])
        for n in names
        if n not in base and catalog["models"][n]["engine"] == "ollama"
    ]
    engines = [
        engine_entry(n, catalog["models"][n])
        for n in names
        if catalog["models"][n]["engine"] != "ollama"
    ]
    return {
        "profile": profile,
        "models": names,
        "models_enabled": [n for n in names if n in base],
        "extra_models": extras,
        "engine_models": engines,
        "plan": plan,
        "table": render_table(plan),
        "catalog": {
            n: {
                "display_name": catalog["models"][n].get("display_name", n),
                "engine": catalog["models"][n]["engine"],
                "tag": catalog["models"][n]["tag"],
                "port": catalog["models"][n].get("port", 11434),
                "capabilities": list(catalog["models"][n]["capabilities"]),
                "license": catalog["models"][n].get("license", "unknown"),
            }
            for n in names
        },
    }


def _selection(args: argparse.Namespace) -> tuple[list[str], str | None]:
    catalog = load_catalog(Path(args.catalog) if args.catalog else None)
    if args.profile:
        profile = resolve_profile(args.profile, catalog)
        return list(profile.get("base", [])) + list(profile.get("extras", [])), args.profile
    if args.model:
        return list(args.model), None
    if args.current:
        return list(args.current), None
    raise CatalogError("select a profile, one or more --model names, or --current")


def cmd_validate(args: argparse.Namespace) -> int:
    catalog = load_catalog(Path(args.catalog) if args.catalog else None)
    print(
        f"ok: {len(catalog['models'])} models, "
        f"{len(catalog['profiles'])} profiles, "
        f"{catalog['budget']['unified_memory_gib']} GiB budget"
    )
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    catalog = load_catalog(Path(args.catalog) if args.catalog else None)
    for name, entry in sorted(catalog["models"].items()):
        caps = ",".join(entry["capabilities"])
        marker = "*" if name in catalog.get("base_models", []) else " "
        print(f"{marker} {name:<28} {entry['engine']:<8} {entry['quant']:<10} {caps}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    catalog = load_catalog(Path(args.catalog) if args.catalog else None)
    entry = catalog["models"].get(args.name)
    if entry is None:
        raise CatalogError(f"unknown model {args.name!r}")
    print(yaml.safe_dump({args.name: entry}, sort_keys=False).rstrip())
    return 0


def cmd_profiles(args: argparse.Namespace) -> int:
    catalog = load_catalog(Path(args.catalog) if args.catalog else None)
    for name, profile in sorted(catalog["profiles"].items()):
        models = list(profile.get("base", [])) + list(profile.get("extras", []))
        plan = build_plan(models, catalog)
        print(
            f"{name:<10} {plan['verdict']:<5} {plan['used_gib']:>6.1f} GiB  "
            f"{profile['description']}"
        )
        print(f"           {', '.join(models) or '(none)'}")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    catalog = load_catalog(Path(args.catalog) if args.catalog else None)
    names, profile_name = _selection(args)
    plan = build_plan(names, catalog)
    if args.json:
        print(json.dumps({"profile": profile_name, "plan": plan}, indent=2))
    elif args.markdown:
        print(f"| Model | Engine | Ctx | Par | Weights | KV | Total | Verdict |")
        print("|---|---|---|---|---|---|---|---|")
        for r in plan["models"]:
            print(
                f'| {r["name"]} | {r["engine"]} | {r["ctx"]} | {r["parallel"]} | '
                f'{r["weights_gib"]} | {r["kv_gib"]} | {r["total_gib"]} | {r["verdict"]} |'
            )
        print("")
        print(
            f'**{plan["verdict"]}** — {plan["used_gib"]} / {plan["budget_gib"]} GiB, '
            f'{plan["slices_used"]} / {plan["slices_max"]} slices'
        )
        for reason in plan["reasons"]:
            print(f"- {reason}")
    else:
        print(render_table(plan))
    return 0 if plan["verdict"] != "FAIL" else 2


def cmd_resolve(args: argparse.Namespace) -> int:
    catalog = load_catalog(Path(args.catalog) if args.catalog else None)
    names, profile_name = _selection(args)
    result = build_resolution(names, catalog, profile_name)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(result["table"])
        print("")
        print("extra_models:")
        for entry in result["extra_models"]:
            print(f"  - {entry['name']} ({entry['tag']}, {entry['size']})")
        if result["engine_models"]:
            print("engine_models:")
            for entry in result["engine_models"]:
                print(f"  - {entry['name']} ({entry['engine']}, {entry['tag']})")
    return 0 if result["plan"]["verdict"] != "FAIL" else 2


def cmd_render_values(args: argparse.Namespace) -> int:
    catalog = load_catalog(Path(args.catalog) if args.catalog else None)
    names, _ = _selection(args)
    result = build_resolution(names, catalog, args.profile)
    if args.json:
        print(json.dumps(result["extra_models"], indent=2))
    else:
        print(yaml.safe_dump(result["extra_models"], sort_keys=False).rstrip())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", help="override catalog path (testing)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="validate the catalog and profiles")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("list", help="list catalog models")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("show", help="show one catalog entry")
    p.add_argument("name")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("profiles", help="list profiles with their fit verdict")
    p.set_defaults(func=cmd_profiles)

    def add_selection(p: argparse.ArgumentParser) -> None:
        p.add_argument("--profile", help="catalog profile name")
        p.add_argument("--model", action="append", default=[], help="model name (repeatable)")
        p.add_argument("--current", nargs="+", default=[], help="plan this explicit set")

    p = sub.add_parser("plan", help="fit a set against memory and GPU slices")
    add_selection(p)
    p.add_argument("--json", action="store_true")
    p.add_argument("--markdown", action="store_true")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("resolve", help="resolve a profile into Ansible variables")
    add_selection(p)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_resolve)

    p = sub.add_parser("render-values", help="emit dgx_extra_models for a selection")
    add_selection(p)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_render_values)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except CatalogError as exc:
        print(f"dgxcatalog: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
