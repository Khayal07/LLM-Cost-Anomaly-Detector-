# LLM Cost Anomaly Detector

🚧 Work in progress.

A real-time monitoring dashboard for LLM API usage — detects cost anomalies (infinite loops, prompt bloat, runaway token usage) before they blow up your bill.

## Idea

LLM API costs can spike silently: a retry loop, a prompt that keeps growing with context, an endpoint suddenly getting hammered. This service ingests every LLM call, baselines normal usage per endpoint/user, and flags anomalies in near real time — with a dashboard to see what happened and why.

## Planned Architecture

- **Ingestion API** — `/log` endpoint (or lightweight SDK wrapper) that records every LLM call: tokens, cost, latency, caller, endpoint
- **Detection layer** — statistical baselining (rolling mean/stddev, z-score/IQR outlier detection) per endpoint/user, structured so a model-based detector can be swapped in later
- **Postgres** — stores call records and flagged incidents
- **Dashboard** — cost over time, cost by model/endpoint, flagged anomalies with drill-down
- **Alerting** — incident records + webhook hook (e.g. Slack)

## Tech Stack

- Python, FastAPI
- PostgreSQL
- Docker / docker-compose
- Dashboard: TBD (React/HTML or Streamlit)

## Status

Currently building out the ingestion and detection layer. Setup instructions, dashboard, and eval results will be added as the project progresses.

## License

MIT