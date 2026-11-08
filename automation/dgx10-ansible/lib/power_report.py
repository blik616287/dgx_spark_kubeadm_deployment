#!/usr/bin/env python3
"""Turn a verify report into power and cost per token.

The verify suite records tokens per second; this multiplies by the measured
draw of the box and divides by the electricity price. Two numbers matter:
tokens per joule (how efficiently the hardware turns power into output) and
dollars per million output tokens (what it costs to run here instead of
renting).

Power draw is measured, not assumed: ``nvidia-smi`` is sampled over a short
window (``--samples``) and the mean is used, so one noisy reading cannot set
the cost figure. Use ``--power-watts`` to override with a reading taken while
the same model was serving, and ``--idle-watts`` to subtract the box's resting
draw.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

POWER_QUERY = ["--query-gpu=power.draw", "--format=csv,noheader,nounits"]


def load_reports(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    if isinstance(data, dict):
        # Accept both the aggregate verify report (`probes`) and a bare list
        # wrapper (`reports`); a single probe report passes through as one row.
        for key in ("reports", "probes"):
            if key in data:
                return data[key]
        return [data]
    if isinstance(data, list):
        return data
    return [data]


def parse_power_samples(text: str) -> list[float]:
    """Parse nvidia-smi's power.draw CSV, skipping headers and N/A rows.

    A looped query prints one line per sample, so summing the lines (the old
    point-sample behaviour) would multiply the draw by the sample count. Each
    line is one reading of each GPU; the caller averages them.
    """
    values: list[float] = []
    for line in text.splitlines():
        # Keep the first field so both `41.5` (nounits) and `41.5 W` parse.
        token = line.strip().split()[0] if line.strip() else ""
        if not token or token.lower().startswith("power.draw"):
            continue
        try:
            values.append(float(token))
        except ValueError:
            continue
    return values


def sample_totals(values: list[float], samples: int) -> list[float]:
    """Group nvidia-smi's per-GPU lines into per-sample box totals.

    ``-c N`` prints N blocks, one line per GPU in each block, so the block
    width is len(values) / N. A single-GPU box (the DGX Spark) is the N ==
    len(values) case and this is a no-op.
    """
    if samples <= 0 or not values:
        return values
    width = max(1, len(values) // samples)
    return [sum(values[i:i + width]) for i in range(0, len(values), width)]


def gpu_watts(samples: int = 1, interval_ms: int = 1000) -> list[float] | None:
    """Return per-sample box totals, or None when nvidia-smi is unavailable."""
    argv = ["nvidia-smi", *POWER_QUERY, "-lms", str(interval_ms), "-c", str(samples)]
    try:
        out = subprocess.run(
            argv, check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        ).stdout.decode()
    except (OSError, subprocess.CalledProcessError):
        return None
    readings = parse_power_samples(out)
    return sample_totals(readings, samples) or None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("report", nargs="?", help="JSON written by the verify suite")
    p.add_argument("--summarize", metavar="FILE",
                   help="summarize a saved nvidia-smi power sample file instead")
    p.add_argument("--power-watts", type=float, help="measured draw while serving")
    p.add_argument("--idle-watts", type=float, default=0.0, help="resting draw to subtract")
    p.add_argument("--samples", type=int, default=10,
                   help="nvidia-smi readings to average (default 10)")
    p.add_argument("--sample-interval-ms", type=int, default=1000)
    p.add_argument("--usd-per-kwh", type=float, default=0.30)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    if args.summarize:
        values = parse_power_samples(Path(args.summarize).read_text())
        if not values:
            print("no power readings in " + args.summarize, file=sys.stderr)
            return 2
        totals = sample_totals(values, min(args.samples, len(values)))
        summary = {
            "readings": len(values),
            "watts_mean": round(sum(totals) / len(totals), 1),
            "watts_min": round(min(totals), 1),
            "watts_max": round(max(totals), 1),
            "watts_spread": round(max(totals) - min(totals), 1),
        }
        if args.json:
            print(json.dumps(summary, indent=2))
        else:
            print(
                f'{summary["readings"]} readings: mean {summary["watts_mean"]} W, '
                f'min {summary["watts_min"]}, max {summary["watts_max"]}, '
                f'spread {summary["watts_spread"]}'
            )
        return 0

    if not args.report:
        p.error("pass a verify report, or --summarize FILE")

    readings: list[float] = []
    if args.power_watts is not None:
        watts = args.power_watts
    else:
        readings = gpu_watts(max(1, args.samples), max(1, args.sample_interval_ms)) or []
        watts = sum(readings) / len(readings) if readings else None
    if watts is None:
        print("no power reading: pass --power-watts or run on the DGX with nvidia-smi", file=sys.stderr)
        return 2
    active_watts = max(watts - args.idle_watts, 1e-9)

    rows = []
    for report in load_reports(Path(args.report)):
        metrics = report.get("metrics") or {}
        tps = metrics.get("tokens_per_s")
        if not tps:
            continue
        tokens_per_joule = tps / active_watts
        usd_per_million = (1_000_000 / tps) * (active_watts / 1000.0) * args.usd_per_kwh
        rows.append({
            "model": report.get("model"),
            "tokens_per_s": tps,
            "active_watts": round(active_watts, 1),
            "tokens_per_joule": round(tokens_per_joule, 3),
            "usd_per_million_tokens": round(usd_per_million, 4),
        })

    if not rows:
        print("no tokens_per_s in the report; run the verify suite first", file=sys.stderr)
        return 2
    sampling = {
        "mode": "samples" if readings else "override",
        "samples": len(readings),
        "watts_mean": round(watts, 1),
        "watts_min": round(min(readings), 1) if readings else None,
        "watts_max": round(max(readings), 1) if readings else None,
        "idle_watts": args.idle_watts,
    }
    if args.json:
        print(json.dumps({"rows": rows, "sampling": sampling}, indent=2))
    else:
        print(f"{'MODEL':<28} {'TOK/S':>8} {'W':>7} {'TOK/J':>8} {'$/1M TOK':>10}")
        print("-" * 65)
        for row in rows:
            print(
                f'{row["model"]:<28} {row["tokens_per_s"]:>8.2f} '
                f'{row["active_watts"]:>7.1f} {row["tokens_per_joule"]:>8.3f} '
                f'{row["usd_per_million_tokens"]:>10.4f}'
            )
        print("")
        if readings:
            print(
                f"power: {len(readings)} samples, mean {sampling['watts_mean']:.1f} W "
                f"(min {sampling['watts_min']:.1f}, max {sampling['watts_max']:.1f})"
            )
        else:
            print(f"power: {watts:.1f} W supplied with --power-watts")
        print(f"electricity at ${args.usd_per_kwh:.2f}/kWh, idle draw {args.idle_watts:.0f} W subtracted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
