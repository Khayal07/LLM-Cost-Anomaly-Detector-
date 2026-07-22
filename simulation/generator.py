"""Synthetic LLM traffic generator with injected, labelled anomalies.

Produces a reproducible (seeded) stream of call records: a warm-up of normal
traffic followed by four injected anomalies — an infinite loop, prompt bloat, a
cost/volume spike, and a single runaway (cost outlier) call. Every record is
labelled with ground truth so the eval harness can score detection.

Usage:
    python -m simulation.generator --send            # POST to a running API
    python -m simulation.generator --send --live     # use real OpenAI tokens
"""
from __future__ import annotations

import argparse
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

# Fixed origin so a given seed always yields identical timestamps.
START = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

ENDPOINTS = ["/chat", "/summarize", "/search", "/agent"]
CALLERS = ["svc-a", "svc-b", "svc-c", "user-x", "user-y"]
MODELS = [("gpt-4o-mini", 0.6), ("gpt-4o", 0.25), ("claude-3-5-sonnet", 0.15)]

NORMAL_MINUTES = 45
CALLS_PER_MIN = 8


@dataclass
class SimRecord:
    ts: datetime
    provider: str
    model: str
    endpoint: str
    caller: str
    tokens_in: int
    tokens_out: int
    request_hash: str | None
    label: str = "normal"
    anomaly_id: int | None = None


@dataclass
class InjectedAnomaly:
    id: int
    type: str
    scope_type: str
    scope_value: str
    onset: datetime
    end: datetime
    record_indices: list[int] = field(default_factory=list)


@dataclass
class Scenario:
    records: list[SimRecord]
    anomalies: list[InjectedAnomaly]


def _pick_model(rng: random.Random) -> tuple[str, str]:
    r = rng.random()
    cum = 0.0
    for name, weight in MODELS:
        cum += weight
        if r <= cum:
            provider = "anthropic" if name.startswith("claude") else "openai"
            return provider, name
    return "openai", "gpt-4o-mini"


def _normal_tokens(rng: random.Random) -> tuple[int, int]:
    tin = max(20, int(rng.lognormvariate(5.9, 0.5)))   # ~ median 365
    tout = max(5, int(tin * rng.uniform(0.2, 0.8)))
    return tin, tout


def _normal_traffic(rng: random.Random) -> list[SimRecord]:
    records: list[SimRecord] = []
    for minute in range(NORMAL_MINUTES):
        n = _poisson(rng, CALLS_PER_MIN)
        for _ in range(n):
            provider, model = _pick_model(rng)
            tin, tout = _normal_tokens(rng)
            ts = START + timedelta(seconds=minute * 60 + rng.uniform(0, 59))
            records.append(
                SimRecord(
                    ts=ts,
                    provider=provider,
                    model=model,
                    endpoint=rng.choice(ENDPOINTS),
                    caller=rng.choice(CALLERS),
                    tokens_in=tin,
                    tokens_out=tout,
                    request_hash=f"norm-{rng.randrange(10**9)}",
                )
            )
    return records


def _poisson(rng: random.Random, lam: float) -> int:
    # Knuth's algorithm using the injected RNG for reproducibility.
    import math

    target = math.exp(-lam)
    k, p = 0, 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= target:
            return k - 1


def _inject_loop(records: list[SimRecord], onset_min: int) -> InjectedAnomaly:
    caller, endpoint = "svc-a", "/agent"
    onset = START + timedelta(minutes=onset_min)
    for i in range(25):  # 25 identical calls in ~30s -> well past threshold
        records.append(
            SimRecord(
                ts=onset + timedelta(seconds=i * 1.2),
                provider="openai",
                model="gpt-4o-mini",
                endpoint=endpoint,
                caller=caller,
                tokens_in=60,
                tokens_out=15,
                request_hash="LOOP-SIGNATURE",
                label="loop",
            )
        )
    return InjectedAnomaly(0, "loop", "caller", caller, onset, onset + timedelta(seconds=30))


def _inject_prompt_bloat(records: list[SimRecord], onset_min: int) -> InjectedAnomaly:
    caller, endpoint = "user-x", "/chat"
    onset = START + timedelta(minutes=onset_min)
    tokens = 700
    end = onset
    for i in range(12):  # context accumulates: grows ~1.5x each turn
        ts = onset + timedelta(seconds=i * 6)
        end = ts
        records.append(
            SimRecord(
                ts=ts,
                provider="openai",
                model="gpt-4o-mini",
                endpoint=endpoint,
                caller=caller,
                tokens_in=int(tokens),
                tokens_out=120,
                request_hash=f"bloat-{i}",
                label="prompt_bloat",
            )
        )
        tokens *= 1.5
    return InjectedAnomaly(0, "prompt_bloat", "caller", caller, onset, end)


def _inject_cost_spike(records: list[SimRecord], onset_min: int) -> InjectedAnomaly:
    endpoint = "/search"
    onset = START + timedelta(minutes=onset_min)
    for i in range(60):  # burst of 60 calls in one minute on a pricier model
        records.append(
            SimRecord(
                ts=onset + timedelta(seconds=i * 0.9),
                provider="openai",
                model="gpt-4o",
                endpoint=endpoint,
                caller="svc-c",
                tokens_in=1200,
                tokens_out=600,
                request_hash=f"spike-{i}",
                label="cost_spike",
            )
        )
    return InjectedAnomaly(0, "cost_spike", "endpoint", endpoint, onset, onset + timedelta(seconds=60))


def _inject_cost_outlier(records: list[SimRecord], onset_min: int) -> InjectedAnomaly:
    endpoint = "/summarize"
    onset = START + timedelta(minutes=onset_min)
    records.append(
        SimRecord(
            ts=onset,
            provider="openai",
            model="gpt-4o",
            endpoint=endpoint,
            caller="svc-b",
            tokens_in=200_000,  # one giant document -> runaway single call
            tokens_out=4000,
            request_hash="outlier-1",
            label="cost_outlier",
        )
    )
    return InjectedAnomaly(0, "cost_outlier", "endpoint", endpoint, onset, onset + timedelta(seconds=1))


def generate(seed: int = 42) -> Scenario:
    """Build a full labelled scenario (deterministic for a given seed)."""
    rng = random.Random(seed)
    records = _normal_traffic(rng)

    anomalies = [
        _inject_loop(records, onset_min=25),
        _inject_prompt_bloat(records, onset_min=30),
        _inject_cost_spike(records, onset_min=35),
        _inject_cost_outlier(records, onset_min=40),
    ]
    for i, anomaly in enumerate(anomalies):
        anomaly.id = i
        for rec in records:
            if rec.label == anomaly.type and anomaly.onset <= rec.ts <= anomaly.end:
                rec.anomaly_id = i

    records.sort(key=lambda r: r.ts)
    for idx, rec in enumerate(records):
        if rec.anomaly_id is not None:
            anomalies[rec.anomaly_id].record_indices.append(idx)
    return Scenario(records=records, anomalies=anomalies)


def to_payload(rec: SimRecord, *, include_ts: bool = True) -> dict:
    payload = {
        "provider": rec.provider,
        "model": rec.model,
        "endpoint": rec.endpoint,
        "caller": rec.caller,
        "tokens_in": rec.tokens_in,
        "tokens_out": rec.tokens_out,
        "request_hash": rec.request_hash,
    }
    if include_ts:
        payload["ts"] = rec.ts.isoformat()
    return payload


def _live_usage(client, prompt_len: int) -> tuple[int, int, int]:
    """Make a real OpenAI call to obtain genuine token counts and latency."""
    prompt = "word " * max(1, prompt_len // 2)
    start = time.perf_counter()
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt[:6000]}],
        max_tokens=32,
    )
    latency = int((time.perf_counter() - start) * 1000)
    usage = resp.usage
    return usage.prompt_tokens, usage.completion_tokens, latency


def send(api_url: str, seed: int, live: bool) -> None:
    import httpx

    scenario = generate(seed)
    print(f"Generated {len(scenario.records)} records, {len(scenario.anomalies)} injected anomalies.")

    oa_client = None
    if live:
        from openai import OpenAI

        if not os.environ.get("OPENAI_API_KEY"):
            raise SystemExit("--live requires OPENAI_API_KEY in the environment.")
        oa_client = OpenAI()
        print("Live mode: token counts and latency will come from real OpenAI calls.")

    with httpx.Client(base_url=api_url.rstrip("/"), timeout=30.0) as http:
        sent = 0
        for rec in scenario.records:
            payload = to_payload(rec)
            if oa_client is not None:
                try:
                    tin, tout, latency = _live_usage(oa_client, rec.tokens_in)
                    payload["tokens_in"], payload["tokens_out"] = tin, tout
                    payload["latency_ms"] = latency
                    payload.pop("cost_usd", None)
                except Exception as exc:  # noqa: BLE001
                    print(f"  live call failed, using synthetic tokens: {exc}")
            resp = http.post("/log", json=payload)
            resp.raise_for_status()
            sent += 1
        print(f"Sent {sent} records to {api_url}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic LLM traffic.")
    parser.add_argument("--send", action="store_true", help="POST records to a running API")
    parser.add_argument("--api", default=os.environ.get("API_URL", "http://localhost:8000"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--live", action="store_true", help="use real OpenAI token counts")
    args = parser.parse_args()

    if args.send:
        send(args.api, args.seed, args.live)
    else:
        scenario = generate(args.seed)
        print(f"Generated {len(scenario.records)} records.")
        for a in scenario.anomalies:
            print(f"  anomaly[{a.id}] {a.type:14s} scope={a.scope_type}:{a.scope_value} "
                  f"records={len(a.record_indices)} onset={a.onset.isoformat()}")


if __name__ == "__main__":
    main()
