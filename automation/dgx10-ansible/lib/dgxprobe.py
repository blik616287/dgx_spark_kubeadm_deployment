#!/usr/bin/env python3
"""Probe one served model through its OpenAI-compatible API.

``ollama list`` proves a manifest exists. This proves the model can answer.
Every request runs inside the predictor pod with ``kubectl exec ... curl`` so
the probe uses the same network path a client would.

Checks are hard by default when the model's catalog entry claims the
capability. Tool calling and structured output are soft unless ``--strict-*``
is passed, because a model can be useful with imperfect adherence and the
report should say so rather than fail the install.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import uuid
from typing import Any

META = "\n__DGX_META__"


class ProbeError(Exception):
    pass


def exec_curl(
    namespace: str,
    deployment: str,
    url: str,
    payload: dict[str, Any] | None = None,
    timeout: int = 300,
) -> tuple[int, dict[str, Any] | str, dict[str, float]]:
    """Run curl in the pod and return (http_status, body, timings)."""
    cmd = [
        "kubectl", "-n", namespace, "exec", "deploy/" + deployment, "--",
        "curl", "-sS", "-m", str(timeout),
        "-w", META + "%{http_code} %{time_starttransfer} %{time_total}",
    ]
    if payload is not None:
        cmd += [
            "-H", "Content-Type: application/json",
            "--data-binary", "@-",
        ]
    cmd.append(url)
    proc = subprocess.run(
        cmd,
        input=json.dumps(payload).encode() if payload is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise ProbeError(
            f"kubectl exec failed for {url}: {proc.stderr.decode(errors='replace').strip()}"
        )
    out = proc.stdout.decode(errors="replace")
    if META not in out:
        raise ProbeError(f"curl produced no metadata for {url}: {out[:300]}")
    body_text, meta = out.rsplit(META, 1)
    parts = meta.strip().split()
    if len(parts) != 3:
        raise ProbeError(f"unexpected curl metadata: {meta!r}")
    status = int(parts[0])
    timings = {
        "ttft_s": float(parts[1]),
        "total_s": float(parts[2]),
    }
    try:
        body: dict[str, Any] | str = json.loads(body_text)
    except json.JSONDecodeError:
        body = body_text
    return status, body, timings


def check(name: str, ok: bool, detail: Any, soft: bool = False) -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "soft": soft, "detail": detail}


def keepalive_payload(model: str, keep_alive: str) -> dict[str, Any]:
    """The Ollama-native request that pins weights in memory.

    The OpenAI-compatible endpoint has no keep-alive knob, so this is the one
    place the probe speaks Ollama's own API. A negative value means "do not
    unload", which is what makes the warm measurement meaningful.
    """
    return {"model": model, "prompt": "", "keep_alive": keep_alive}


def warm_up(args: argparse.Namespace, base: str) -> dict[str, Any] | None:
    """Pin the weights (Ollama only) and return a soft check, if attempted."""
    if args.engine != "ollama" or args.warmup <= 0:
        return None
    try:
        status, body, timings = exec_curl(
            args.namespace,
            args.deployment,
            base + "/api/generate",
            keepalive_payload(args.model, args.keep_alive),
            timeout=args.timeout,
        )
    except ProbeError as exc:
        return check("keep_alive", False, str(exc), soft=True)
    return check(
        "keep_alive",
        status == 200,
        {"status": status, "keep_alive": args.keep_alive, "load_s": timings["total_s"]},
        soft=True,
    )


def probe(args: argparse.Namespace) -> dict[str, Any]:
    base = f"http://localhost:{args.port}"
    checks: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {}

    # ── model listing ────────────────────────────────────────────────
    status, body, _ = exec_curl(
        args.namespace, args.deployment, base + "/v1/models", timeout=args.timeout
    )
    ids: list[str] = []
    if isinstance(body, dict):
        ids = [m.get("id", "") for m in body.get("data", []) if isinstance(m, dict)]
    listed = any(args.model == i or args.model.startswith(i) or i.startswith(args.model.split(":")[0]) for i in ids)
    checks.append(check("models", status == 200 and listed, {"status": status, "ids": ids}))

    capabilities = set(args.capability)
    do_chat = bool(capabilities & {"chat", "tools"})

    if do_chat:
        warm_check = warm_up(args, base)
        if warm_check is not None:
            checks.append(warm_check)

        chat_payload = {
            "model": args.model,
            "messages": [{"role": "user", "content": "Reply with exactly: DGX10-OK"}],
            "max_tokens": 16,
            "temperature": 0,
        }
        # The first request pays the weight-load cost; the rest measure the
        # steady state. Recording both means a slow first token is visible as
        # a cold load rather than a slow model.
        attempts: list[tuple[int, Any, dict[str, float]]] = []
        for _ in range(max(0, args.warmup) + 1):
            status, body, timings = exec_curl(
                args.namespace, args.deployment, base + "/v1/chat/completions",
                chat_payload, timeout=args.timeout,
            )
            attempts.append((status, body, timings))
            if status != 200:
                break
        status, body, timings = attempts[-1]
        content = ""
        usage = {}
        if isinstance(body, dict):
            try:
                content = body["choices"][0]["message"].get("content") or ""
            except (KeyError, IndexError, TypeError):
                content = ""
            usage = body.get("usage") or {}
        checks.append(check(
            "chat",
            status == 200 and bool(content.strip()),
            {"status": status, "content": content[:200]},
        ))
        metrics["ttft_s"] = timings["ttft_s"]
        metrics["total_s"] = timings["total_s"]
        if len(attempts) > 1:
            metrics["cold_s"] = attempts[0][2]["total_s"]
            warm = [a[2]["total_s"] for a in attempts[1:] if a[0] == 200]
            if warm:
                metrics["warm_s"] = round(sum(warm) / len(warm), 3)
            metrics["warm_requests"] = len(warm)
        completion_tokens = usage.get("completion_tokens")
        if completion_tokens and timings["total_s"] > 0:
            metrics["completion_tokens"] = completion_tokens
            metrics["tokens_per_s"] = round(completion_tokens / timings["total_s"], 2)

        # Tool calling is a separate request on top of the warm chat path.
        if "tools" in capabilities:
            tools_payload = {
                "model": args.model,
                "messages": [
                    {"role": "user", "content": "What is the weather in Paris? Use the tool."}
                ],
                "tools": [{
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "description": "Get the current weather for a city",
                        "parameters": {
                            "type": "object",
                            "properties": {"city": {"type": "string"}},
                            "required": ["city"],
                        },
                    },
                }],
                "tool_choice": "auto",
                "max_tokens": 128,
                "temperature": 0,
            }
            status, body, _ = exec_curl(
                args.namespace, args.deployment, base + "/v1/chat/completions", tools_payload,
                timeout=args.timeout,
            )
            tool_calls = []
            if isinstance(body, dict):
                try:
                    tool_calls = body["choices"][0]["message"].get("tool_calls") or []
                except (KeyError, IndexError, TypeError):
                    tool_calls = []
            checks.append(check(
                "tools",
                status == 200 and (bool(tool_calls) or args.strict_tools is False),
                {"status": status, "tool_calls": tool_calls[:1]},
                soft=not args.strict_tools,
            ))

        if args.structured:
            structured_payload = {
                "model": args.model,
                "messages": [{"role": "user", "content": 'Return exactly the JSON {"ok": true}'}],
                "response_format": {"type": "json_object"},
                "max_tokens": 64,
                "temperature": 0,
            }
            status, body, _ = exec_curl(
                args.namespace, args.deployment, base + "/v1/chat/completions",
                structured_payload, timeout=args.timeout,
            )
            content = ""
            if isinstance(body, dict):
                try:
                    content = body["choices"][0]["message"].get("content") or ""
                except (KeyError, IndexError, TypeError):
                    content = ""
            parsed = False
            try:
                json.loads(content)
                parsed = True
            except (json.JSONDecodeError, TypeError):
                parsed = False
            checks.append(check(
                "structured_output",
                status == 200 and parsed,
                {"status": status, "content": content[:200]},
                soft=not args.strict_structured,
            ))

        if args.long_context:
            needle = "DGX-" + uuid.uuid4().hex[:10]
            filler = ("The archive records routine maintenance. " * 220)
            prompt = (
                f"{needle}\n\n{filler}\n\n"
                "The code near the start of this message is the only thing I need. "
                "Reply with only that code and nothing else."
            )
            needle_payload = {
                "model": args.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 24,
                "temperature": 0,
            }
            status, body, _ = exec_curl(
                args.namespace, args.deployment, base + "/v1/chat/completions",
                needle_payload, timeout=600,
            )
            content = ""
            if isinstance(body, dict):
                try:
                    content = body["choices"][0]["message"].get("content") or ""
                except (KeyError, IndexError, TypeError):
                    content = ""
            checks.append(check(
                "long_context",
                status == 200 and needle in content,
                {"status": status, "needle": needle, "content": content[:200]},
            ))

        if "vision" in capabilities:
            checks.append(check(
                "vision",
                True,
                "not exercised: the probe does not synthesize an image",
                soft=True,
            ))

    if "embedding" in capabilities:
        embed_payload = {"model": args.model, "input": "The quick brown fox."}
        status, body, _ = exec_curl(
            args.namespace, args.deployment, base + "/v1/embeddings", embed_payload,
            timeout=args.timeout,
        )
        vector: list[float] = []
        if isinstance(body, dict):
            try:
                vector = body["data"][0]["embedding"]
            except (KeyError, IndexError, TypeError):
                vector = []
        metrics["embedding_dim"] = len(vector)
        checks.append(check(
            "embeddings",
            status == 200 and len(vector) > 0,
            {"status": status, "dimension": len(vector)},
        ))

    if "rerank" in capabilities:
        rerank_payload = {
            "model": args.model,
            "query": "What is the capital of France?",
            "documents": ["Paris is the capital of France.", "Bananas are yellow."],
        }
        # vLLM exposes both spellings across releases; accept either.
        status, body, _ = exec_curl(
            args.namespace, args.deployment, base + "/v1/rerank", rerank_payload,
            timeout=args.timeout,
        )
        if status == 404:
            status, body, _ = exec_curl(
                args.namespace, args.deployment, base + "/rerank", rerank_payload,
                timeout=args.timeout,
            )
        results = body.get("results") if isinstance(body, dict) else None
        checks.append(check(
            "rerank",
            status == 200 and bool(results),
            {"status": status, "results": (results or [])[:2]},
        ))

    hard_failures = [c for c in checks if not c["ok"] and not c["soft"]]
    return {
        "model": args.model,
        "deployment": args.deployment,
        "engine": args.engine,
        "ok": not hard_failures,
        "checks": checks,
        "metrics": metrics,
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--namespace", default="llm-serving")
    p.add_argument("--deployment", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--port", type=int, default=11434)
    p.add_argument("--timeout", type=int, default=300, help="per-request timeout in seconds")
    p.add_argument("--engine", default="ollama")
    p.add_argument("--capability", action="append", default=[])
    p.add_argument("--long-context", action="store_true")
    p.add_argument("--structured", action="store_true")
    p.add_argument("--strict-tools", action="store_true")
    p.add_argument("--strict-structured", action="store_true")
    p.add_argument("--warmup", type=int, default=2,
                   help="requests before the measured one (0 disables warm-up)")
    p.add_argument("--keep-alive", default="-1",
                   help="Ollama keep_alive value used to pin the weights")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    started = time.time()
    try:
        report = probe(args)
    except ProbeError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    report["elapsed_s"] = round(time.time() - started, 2)
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
