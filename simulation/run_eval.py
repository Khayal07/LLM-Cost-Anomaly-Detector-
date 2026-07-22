"""Evaluate the detection layer against a labelled synthetic scenario.

Replays the generated traffic through the real detection engine (mirroring
ingestion), then scores results using ground truth. An incident is matched to an
anomaly via the trigger record's label, so scoring is unambiguous:

  * true positive  — incident triggered by a record belonging to an anomaly
  * false positive — incident triggered by a normal record
  * recall         — fraction of injected anomalies that produced any incident
  * time-to-detection — seconds and #records from an anomaly's onset to its
                        first incident

Outputs ``eval/report.md`` and ``eval/report.json``.

    python -m simulation.run_eval [--seed 42] [--out eval]
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def _configure_fresh_db() -> Path:
    path = Path(tempfile.gettempdir()) / f"costmonitor_eval_{os.getpid()}.db"
    if path.exists():
        path.unlink()
    os.environ["DATABASE_URL"] = f"sqlite:///{path.as_posix()}"
    return path


def _f(x: float) -> float:
    return round(float(x), 4)


def run(seed: int) -> dict:
    db_path = _configure_fresh_db()

    # Imports happen after DATABASE_URL is set so the engine binds to the temp DB.
    from sqlalchemy import select

    from app.db import Base, SessionLocal, engine
    from app.detection.engine import run_detection
    from app.models import CallRecord, Incident
    from app.pricing import compute_cost
    from simulation.generator import generate

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    scenario = generate(seed)
    session = SessionLocal()

    id_to_anomaly: dict[int, int | None] = {}
    id_to_index: dict[int, int] = {}

    for idx, rec in enumerate(scenario.records):
        cr = CallRecord(
            ts=rec.ts,
            provider=rec.provider,
            model=rec.model,
            endpoint=rec.endpoint,
            caller=rec.caller,
            tokens_in=rec.tokens_in,
            tokens_out=rec.tokens_out,
            total_tokens=rec.tokens_in + rec.tokens_out,
            cost_usd=compute_cost(rec.model, rec.tokens_in, rec.tokens_out),
            latency_ms=0,
            request_hash=rec.request_hash,
            status="success",
        )
        session.add(cr)
        session.flush()
        id_to_anomaly[cr.id] = rec.anomaly_id
        id_to_index[cr.id] = idx
        run_detection(session, cr)
        session.commit()

    incidents = list(session.execute(select(Incident).order_by(Incident.detected_at)).scalars())

    # --- classify incidents ------------------------------------------------
    tp_incidents = 0
    fp_incidents = 0
    matched_by_anomaly: dict[int, list[Incident]] = {a.id: [] for a in scenario.anomalies}
    for inc in incidents:
        anom_id = id_to_anomaly.get(inc.trigger_record_id)
        if anom_id is None:
            fp_incidents += 1
        else:
            tp_incidents += 1
            matched_by_anomaly[anom_id].append(inc)

    # --- per-anomaly detail ------------------------------------------------
    per_anomaly = []
    for a in scenario.anomalies:
        matches = matched_by_anomaly[a.id]
        detected = len(matches) > 0
        entry = {
            "id": a.id,
            "type": a.type,
            "scope": f"{a.scope_type}:{a.scope_value}",
            "detected": detected,
            "type_match": any(inc.type == a.type for inc in matches),
            "ttd_seconds": None,
            "records_to_detection": None,
        }
        if detected:
            first = min(matches, key=lambda i: i.detected_at)
            onset = a.onset if a.onset.tzinfo else a.onset.replace(tzinfo=timezone.utc)
            det = first.detected_at if first.detected_at.tzinfo else first.detected_at.replace(tzinfo=timezone.utc)
            entry["ttd_seconds"] = _f((det - onset).total_seconds())
            trigger_idx = id_to_index.get(first.trigger_record_id, -1)
            entry["records_to_detection"] = sum(
                1 for i in a.record_indices if i <= trigger_idx
            )
        per_anomaly.append(entry)

    # --- aggregate metrics -------------------------------------------------
    total_anomalies = len(scenario.anomalies)
    detected_anomalies = sum(1 for e in per_anomaly if e["detected"])
    normal_records = sum(1 for r in scenario.records if r.anomaly_id is None)

    recall = detected_anomalies / total_anomalies if total_anomalies else 0.0
    precision = tp_incidents / (tp_incidents + fp_incidents) if incidents else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    per_type: dict[str, dict] = {}
    for e in per_anomaly:
        bucket = per_type.setdefault(e["type"], {"total": 0, "detected": 0, "ttd": [], "recs": []})
        bucket["total"] += 1
        bucket["detected"] += int(e["detected"])
        if e["detected"]:
            bucket["ttd"].append(e["ttd_seconds"])
            bucket["recs"].append(e["records_to_detection"])
    per_type_out = {
        t: {
            "total": b["total"],
            "detected": b["detected"],
            "recall": _f(b["detected"] / b["total"]) if b["total"] else 0.0,
            "avg_ttd_seconds": _f(sum(b["ttd"]) / len(b["ttd"])) if b["ttd"] else None,
            "avg_records_to_detection": _f(sum(b["recs"]) / len(b["recs"])) if b["recs"] else None,
        }
        for t, b in per_type.items()
    }

    session.close()
    if db_path.exists():
        try:
            db_path.unlink()
        except OSError:
            pass

    return {
        "seed": seed,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "totals": {
            "records": len(scenario.records),
            "normal_records": normal_records,
            "injected_anomalies": total_anomalies,
            "incidents_raised": len(incidents),
        },
        "overall": {
            "precision": _f(precision),
            "recall": _f(recall),
            "f1": _f(f1),
            "true_positive_incidents": tp_incidents,
            "false_positive_incidents": fp_incidents,
            "fp_per_1k_normal_calls": _f(fp_incidents / normal_records * 1000) if normal_records else 0.0,
        },
        "per_type": per_type_out,
        "anomalies": per_anomaly,
    }


def _to_markdown(report: dict) -> str:
    o = report["overall"]
    t = report["totals"]
    lines = [
        "# LLM Cost Anomaly Detection — Eval Report",
        "",
        f"_Generated {report['generated_at']} · seed={report['seed']}_",
        "",
        "## Summary",
        "",
        f"- **Records replayed:** {t['records']} ({t['normal_records']} normal)",
        f"- **Injected anomalies:** {t['injected_anomalies']}",
        f"- **Incidents raised:** {t['incidents_raised']}",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Precision | {o['precision']:.2f} |",
        f"| Recall | {o['recall']:.2f} |",
        f"| F1 | {o['f1']:.2f} |",
        f"| True-positive incidents | {o['true_positive_incidents']} |",
        f"| False-positive incidents | {o['false_positive_incidents']} |",
        f"| False positives / 1k normal calls | {o['fp_per_1k_normal_calls']:.2f} |",
        "",
        "## By anomaly type",
        "",
        "| Type | Detected | Recall | Avg time-to-detect (s) | Avg records-to-detect |",
        "|---|---|---|---|---|",
    ]
    for name, m in report["per_type"].items():
        lines.append(
            f"| {name} | {m['detected']}/{m['total']} | {m['recall']:.2f} | "
            f"{m['avg_ttd_seconds'] if m['avg_ttd_seconds'] is not None else '—'} | "
            f"{m['avg_records_to_detection'] if m['avg_records_to_detection'] is not None else '—'} |"
        )
    lines += ["", "## Per-anomaly detail", "", "| # | Type | Scope | Detected | Type match | TTD (s) | Records |", "|---|---|---|---|---|---|---|"]
    for a in report["anomalies"]:
        lines.append(
            f"| {a['id']} | {a['type']} | {a['scope']} | {'✅' if a['detected'] else '❌'} | "
            f"{'✅' if a['type_match'] else '—'} | "
            f"{a['ttd_seconds'] if a['ttd_seconds'] is not None else '—'} | "
            f"{a['records_to_detection'] if a['records_to_detection'] is not None else '—'} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the detection eval.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", default="eval")
    args = parser.parse_args()

    report = run(args.seed)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out_dir / "report.md").write_text(_to_markdown(report), encoding="utf-8")

    o = report["overall"]
    print(f"Precision={o['precision']:.2f} Recall={o['recall']:.2f} F1={o['f1']:.2f} "
          f"FP={o['false_positive_incidents']} -> wrote {out_dir}/report.md")


if __name__ == "__main__":
    main()
