#!/usr/bin/env python3
"""A small, fixed report card for a served chat model.

The verify probe answers "does it serve?". This answers "is what it serves
usable?" with a handful of cases whose answers are checkable without a judge
model: arithmetic, exact instruction following, and a JSON shape. The cases are
deliberately easy; a model that fails them will fail real work, and a model
that passes them has not thereby proved anything harder.

Run it inside the framework against one deployment. Results are a report card,
not a benchmark: the same prompt and the same scoring, recorded so a change to
weights or runtime is visible as a diff.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dgxprobe import ProbeError, exec_curl  # noqa: E402


def _exact(expected: str) -> Callable[[str], bool]:
    return lambda text: text.strip().lower() == expected.lower()


def _contains(expected: str) -> Callable[[str], bool]:
    return lambda text: expected.lower() in text.lower()


def _json_shape(keys: list[str]) -> Callable[[str], bool]:
    def check(text: str) -> bool:
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return False
        return isinstance(data, dict) and all(k in data for k in keys)

    return check


CASES: list[dict[str, Any]] = [
    {
        "name": "exact_instruction",
        "prompt": "Reply with exactly: DGX10-OK",
        "check": _exact("DGX10-OK"),
        "max_tokens": 16,
    },
    {
        "name": "arithmetic",
        "prompt": "What is 17 * 23? Reply with only the number.",
        "check": _contains("391"),
        "max_tokens": 32,
    },
    {
        "name": "capital",
        "prompt": "What is the capital of France? Reply with only the city name.",
        "check": _contains("paris"),
        "max_tokens": 32,
    },
    {
        "name": "json_shape",
        "prompt": (
            'Return only a JSON object with exactly two keys: "status" set to '
            '"ok" and "count" set to 3. No prose, no code fence.'
        ),
        "check": _json_shape(["status", "count"]),
        "max_tokens": 64,
        "temperature": 0,
    },
    {
        "name": "single_word",
        "prompt": (
            "The sky on a clear day is which colour? Reply with only that one "
            "word, lowercase."
        ),
        "check": _exact("blue"),
        "max_tokens": 16,
    },
]


def run_case(args: argparse.Namespace, case: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "model": args.model,
        "messages": [{"role": "user", "content": case["prompt"]}],
        "max_tokens": case.get("max_tokens", 64),
        "temperature": case.get("temperature", 0),
    }
    started = time.time()
    try:
        status, body, timings = exec_curl(
            args.namespace,
            args.deployment,
            f"http://localhost:{args.port}/v1/chat/completions",
            payload,
            timeout=args.timeout,
        )
    except ProbeError as exc:
        return {
            "name": case["name"],
            "ok": False,
            "error": str(exc),
            "elapsed_s": round(time.time() - started, 2),
        }
    content = ""
    if isinstance(body, dict):
        try:
            content = body["choices"][0]["message"].get("content") or ""
        except (KeyError, IndexError, TypeError):
            content = ""
    passed = status == 200 and bool(case["check"](content))
    return {
        "name": case["name"],
        "ok": passed,
        "status": status,
        "content": content[:300],
        "ttft_s": timings["ttft_s"],
        "elapsed_s": round(time.time() - started, 2),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--namespace", default="llm-serving")
    p.add_argument("--deployment", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--port", type=int, default=11434)
    p.add_argument("--engine", default="ollama")
    p.add_argument("--timeout", type=int, default=300)
    p.add_argument("--case", action="append", default=[],
                   help="run only these case names (repeatable)")
    args = p.parse_args(argv)

    selected = [c for c in CASES if not args.case or c["name"] in args.case]
    if not selected:
        print(f"no such case; known: {', '.join(c['name'] for c in CASES)}", file=sys.stderr)
        return 2

    started = time.time()
    results = [run_case(args, case) for case in selected]
    passed = sum(1 for r in results if r["ok"])
    report = {
        "model": args.model,
        "deployment": args.deployment,
        "engine": args.engine,
        "cases": results,
        "passed": passed,
        "total": len(results),
        "score": round(passed / len(results), 3),
        "elapsed_s": round(time.time() - started, 2),
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
