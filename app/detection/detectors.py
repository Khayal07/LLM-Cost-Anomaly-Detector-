"""Concrete statistical detectors.

Each detector inspects a freshly ingested record against a rolling baseline
drawn from recent history and, if the record looks anomalous, returns an
``IncidentCandidate``. All thresholds come from settings so behaviour is tunable
without code changes.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import func, select

from app.detection.base import (
    BaseDetector,
    DetectionContext,
    IncidentCandidate,
    epoch,
    severity_from_zscore,
)
from app.detection.stats import iqr_bounds, mean_std, median, zscore
from app.models import CallRecord


class CostSpikeDetector(BaseDetector):
    """Aggregate volume/cost surge on an endpoint (many calls, not one big one)."""

    type = "cost_spike"

    def evaluate(self, ctx: DetectionContext) -> IncidentCandidate | None:
        s, rec = ctx.settings, ctx.record
        start = rec.ts - timedelta(seconds=s.baseline_window_seconds)
        bucket = s.cost_spike_bucket_seconds

        rows = ctx.session.execute(
            select(CallRecord.ts, CallRecord.cost_usd).where(
                CallRecord.endpoint == rec.endpoint,
                CallRecord.ts >= start,
                CallRecord.ts <= rec.ts,
            )
        ).all()

        sums: dict[int, float] = defaultdict(float)
        for ts, cost in rows:
            sums[int(epoch(ts) // bucket)] += float(cost)

        current_key = int(epoch(rec.ts) // bucket)
        current_sum = sums.pop(current_key, 0.0)
        hist = list(sums.values())

        mean, std, n = mean_std(hist)
        if n < s.min_samples:
            return None
        z = zscore(current_sum, mean, std)
        if z <= s.z_score_threshold:
            return None

        return IncidentCandidate(
            type=self.type,
            scope_type="endpoint",
            scope_value=rec.endpoint,
            severity=severity_from_zscore(z, s.z_score_threshold),
            score=round(z, 3),
            baseline={"mean": mean, "stddev": std, "n": n, "bucket_seconds": bucket},
            observed={"bucket_cost": round(current_sum, 6)},
            window_start=start,
            window_end=rec.ts,
            message=(
                f"Cost spike on '{rec.endpoint}': ${current_sum:.4f} in the last "
                f"{bucket}s vs baseline ${mean:.4f} (z={z:.1f})."
            ),
            trigger_record_id=rec.id,
        )


class LoopSignatureDetector(BaseDetector):
    """Repeated identical calls — infinite loop / retry storm."""

    type = "loop"

    def evaluate(self, ctx: DetectionContext) -> IncidentCandidate | None:
        s, rec = ctx.settings, ctx.record
        if not rec.request_hash:
            return None
        start = rec.ts - timedelta(seconds=s.loop_window_seconds)

        count = ctx.session.execute(
            select(func.count())
            .select_from(CallRecord)
            .where(
                CallRecord.request_hash == rec.request_hash,
                CallRecord.caller == rec.caller,
                CallRecord.endpoint == rec.endpoint,
                CallRecord.ts >= start,
                CallRecord.ts <= rec.ts,
            )
        ).scalar_one()

        if count < s.loop_count_threshold:
            return None

        return IncidentCandidate(
            type=self.type,
            scope_type="caller",
            scope_value=rec.caller,
            severity="high",
            score=float(count),
            baseline={"threshold": s.loop_count_threshold, "window_seconds": s.loop_window_seconds},
            observed={"count": count, "request_hash": rec.request_hash, "endpoint": rec.endpoint},
            window_start=start,
            window_end=rec.ts,
            message=(
                f"Loop signature: {count} identical calls from '{rec.caller}' to "
                f"'{rec.endpoint}' within {s.loop_window_seconds}s."
            ),
            trigger_record_id=rec.id,
        )


class TokenGrowthDetector(BaseDetector):
    """Prompt bloat: a caller's input tokens balloon vs their recent median."""

    type = "prompt_bloat"

    def evaluate(self, ctx: DetectionContext) -> IncidentCandidate | None:
        s, rec = ctx.settings, ctx.record
        start = rec.ts - timedelta(seconds=s.baseline_window_seconds)

        vals = ctx.session.execute(
            select(CallRecord.tokens_in).where(
                CallRecord.caller == rec.caller,
                CallRecord.ts >= start,
                CallRecord.ts <= rec.ts,
                CallRecord.id != rec.id,
            )
        ).scalars().all()

        if len(vals) < s.min_samples:
            return None
        med = median(vals)
        ratio = rec.tokens_in / max(med, 1.0)
        if ratio < s.token_growth_ratio:
            return None

        return IncidentCandidate(
            type=self.type,
            scope_type="caller",
            scope_value=rec.caller,
            severity="high" if ratio >= 2 * s.token_growth_ratio else "medium",
            score=round(ratio, 3),
            baseline={"median_tokens_in": med, "n": len(vals)},
            observed={"tokens_in": rec.tokens_in, "ratio": round(ratio, 2)},
            window_start=start,
            window_end=rec.ts,
            message=(
                f"Prompt bloat from '{rec.caller}': {rec.tokens_in} input tokens is "
                f"{ratio:.1f}x the recent median of {med:.0f}."
            ),
            trigger_record_id=rec.id,
        )


class CostOutlierDetector(BaseDetector):
    """A single runaway call: per-request cost far above the endpoint baseline."""

    type = "cost_outlier"

    def evaluate(self, ctx: DetectionContext) -> IncidentCandidate | None:
        s, rec = ctx.settings, ctx.record
        start = rec.ts - timedelta(seconds=s.baseline_window_seconds)

        vals = [
            float(v)
            for v in ctx.session.execute(
                select(CallRecord.cost_usd).where(
                    CallRecord.endpoint == rec.endpoint,
                    CallRecord.ts >= start,
                    CallRecord.ts <= rec.ts,
                    CallRecord.id != rec.id,
                )
            ).scalars().all()
        ]

        if len(vals) < s.min_samples:
            return None

        cost = float(rec.cost_usd)
        mean, std, n = mean_std(vals)
        z = zscore(cost, mean, std)
        _, upper = iqr_bounds(vals, s.iqr_multiplier)

        if z <= s.z_score_threshold and cost <= upper:
            return None

        return IncidentCandidate(
            type=self.type,
            scope_type="endpoint",
            scope_value=rec.endpoint,
            severity=severity_from_zscore(z, s.z_score_threshold) if z > 0 else "medium",
            score=round(z, 3),
            baseline={"mean": mean, "stddev": std, "n": n, "iqr_upper": round(upper, 6)},
            observed={"cost_usd": round(cost, 6)},
            window_start=start,
            window_end=rec.ts,
            message=(
                f"Cost outlier on '{rec.endpoint}': ${cost:.4f} vs baseline "
                f"${mean:.4f} (z={z:.1f})."
            ),
            trigger_record_id=rec.id,
        )


# Default registry — order is cosmetic; all run on every record.
ALL_DETECTORS: list[BaseDetector] = [
    CostSpikeDetector(),
    LoopSignatureDetector(),
    TokenGrowthDetector(),
    CostOutlierDetector(),
]
