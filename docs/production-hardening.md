# Production Hardening Guide

This document describes how to close the remaining hardening gaps for OpenAgent.
It separates **repo-solvable** controls from **deployment/infra controls**.

## Status summary

| Area | In-repo baseline | External/infra required to close |
|---|---|---|
| F-04 TLS/mTLS | App binds HTTP; token/HMAC/authz checks | TLS termination + mTLS at reverse proxy/load balancer |
| F-04 distributed rate limit/WAF | Per-process fixed-window limit | Edge/WAF/distributed limiter (Redis/Envoy/Cloud WAF) |
| F-04 tamper-proof audit | Hash-chained `logs/ingress.jsonl` | WORM/immutable store or SIEM ingestion with retention |
| F-04 authz depth | Session/source/prefix allowlists | Full RBAC/policy model and operational token lifecycle |
| F-06/F-10 prompt injection | Regex scan, recall filter, untrusted memory framing | Optional classifier/model hook; cannot guarantee safety |
| F-07 provenance/lineage | `wiki/state.json` snapshot + markdown fallback | Full append-only provenance/event history and migrations |
| Tests/ops | pytest unit/integration tests | TLS-proxy e2e, load/stress, CI policy gates |

## 1) F-04 Infra/Product-dependent

### TLS termination / mTLS

- Run `openagent serve` on a private interface or internal network only.
- Put Caddy/nginx/Envoy in front for TLS. See `deploy/Caddyfile` and `deploy/nginx.conf.example`.
- For mTLS, configure proxy client cert verification against your internal CA.
- Forward verified identity headers only from trusted proxy hops (e.g. `X-Client-Subject`), and strip/overwrite them at the edge.
- Add an e2e test that starts proxy + OpenAgent and verifies: TLS required, invalid cert rejected, valid cert accepted.

### Distributed rate limiting / WAF

- Keep OpenAgent `--rate-limit` as a last-resort app limit.
- Enforce primary rate limits at edge (Caddy plugin, Envoy, nginx/OpenResty, cloud WAF/API gateway).
- For multi-instance OpenAgent, use shared state (Redis) in edge limiter; app-local limiter is per process.
- Add WAF rules for request size, method/path, content-type, bot signatures, and source IP reputation as appropriate.
- Close with load tests proving 429 behavior and no queue exhaustion under burst.

### Tamper-proof audit store

- Treat `logs/ingress.jsonl` hash chain as tamper-evident, not immutable.
- Ship logs to immutable/WORM storage (S3 Object Lock, GCS Bucket Lock, Azure immutable blob, or SIEM).
- Include host/instance identity, request ID, and hash chain fields in shipped records.
- Restrict write/delete permissions; alert on hash-chain breaks or missing sequence gaps.
- Close with a runbook and periodic restore/audit verification.

## 2) F-04 Authz depth

Target model: **token -> principal/role -> scopes -> allowed sessions/sources/actions**.

Recommended config shape:

```json
{
  "principals": [
    {
      "name": "webhook-prod",
      "token_env": "OPENAGENT_INGRESS_TOKEN_PROD",
      "scopes": ["events:write"],
      "allow_sessions": ["app:*"],
      "allow_sources": ["http", "slack"]
    }
  ]
}
```

Implementation steps:

1. Add `openagent/authz.py` policy module and config loader.
2. Evaluate policy on every ingress request before enqueue.
3. Add scopes for admin commands (`/dream`, `/revert`, `/clear`) and owner-only actions.
4. Support token rotation (multiple active tokens, expiry metadata optional).
5. Default deny for unknown tokens/sessions/sources when policy is configured.

Close criteria: unit tests for policy matrix + serve integration tests for 401/403/202 cases and rotation.

## 3) F-06/F-10 Prompt injection / memory taint

OpenAgent can reduce risk, but cannot guarantee prompt-injection safety.

In-repo steps:

1. Define `ThreatScanner` interface: `scan(text, context) -> ThreatVerdict`.
2. Keep regex scanner as baseline; allow optional model/classifier scanner.
3. Scan on all memory write paths (facts, episodes, user facts, imported wiki) and on recall/render.
4. Add taint/provenance metadata to memory records/snapshots: `source`, `trusted`, `ingested_at`, `scanner`, `verdict`.
5. Render recalled memory as untrusted data blocks; never as system instructions.
6. Maintain `tests/adversarial_corpus/` with known injection strings and false-positive benign cases.

Close criteria: adversarial corpus CI job + documented residual risk.

## 4) F-07 Provenance / lineage

Current: `wiki/state.json` snapshot + markdown export/sync.

Target: append-only memory event/history table, e.g. `memory_events(id, ts, op, entity_type, entity_id, payload_json, run_id, commit_sha, source)`.

Steps:

1. Add schema migration with backward compatibility.
2. Record fact/episode add/update/delete/revert events.
3. Export/import provenance-aware snapshots.
4. Rebuild current state from event log or verify snapshot against log.
5. Add migration/revert/legacy snapshot tests.

Close criteria: deterministic replay/rebuild tests and revert lineage assertions.

## 5) Tests/ops

CI should include:

- Unit/integration tests (`pytest -q`) on supported Python versions.
- Adversarial corpus and authz matrix tests.
- Cron/DST multi-zone tests with tzdata installed.
- Load/stress smoke (rate limit, queue saturation, concurrent ingress).
- Docker compose smoke (`docker compose config`, image build).
- TLS-proxy e2e (docker-compose with Caddy/nginx cert fixtures).

## Operator checklist

- [ ] Real domain + TLS certs configured.
- [ ] mTLS CA and client certs issued/rotated.
- [ ] Edge rate limiting/WAF enabled.
- [ ] Audit logs shipped to WORM/SIEM with alerts.
- [ ] Authz policy configured with least privilege.
- [ ] Token/HMAC secrets rotated and stored in secret manager.
- [ ] CI green including adversarial and e2e jobs.

## MCP bridge hardening (persistent patterns)

- MCP is disabled unless `OPENAGENT_MCP_URL` is configured.
- `McpBridge` enforces `http/https`, rejects redirects, caps response size, and blocks private/loopback/resolved-private hosts by default.
- Explicit opt-ins:
  - `OPENAGENT_MCP_ALLOW_PRIVATE=1` — allow loopback/private targets (trusted local MCP servers only).
  - `OPENAGENT_MCP_ALLOWED_HOSTS=host1,host2` — hostname allowlist policy.
- Remote MCP tools are still guard-gated: `readOnlyHint=true` may be allowed; non-read-only/unknown tools require approval or are denied per bridge/guard policy.

## Status update (review 18ZXu8JDjh0UA-fAe_-pYPwFyzntYK8_m follow-up)

### Closed/implemented in-repo
- **Trusted proxy IP policy**: `openagent serve --trusted-proxies` / `OPENAGENT_TRUSTED_PROXIES` now only honors `X-Forwarded-For` from trusted proxy peers; direct peer IP is used otherwise.
- **Ingress reply_to validation**: HTTP ingress accepts only valid `stdout|local|cli` reply targets, preventing external exfiltration via unvalidated reply_to.
- **Threaded HTTP ingress**: serve uses `ThreadingHTTPServer` to reduce single-request blocking; handler timeout remains configured. Full slowloris protection still requires a reverse proxy/WAF.
- **Audit hash-chain locking**: ingress audit hash chaining is computed/written under a lock.
- **Rate limiter pruning**: in-memory limiter prunes stale keys to bound growth. Distributed/shared rate limiting remains deployment-specific.
- **Durable approval resume (best-effort)**: parked approvals persist resume state (`resume_state`) including messages/system/held call; approval answers can resume the turn via LLM loop continuation, reducing duplicate side effects. A reverse proxy and durable process manager are still recommended.
- **Pluggable threat scanner runtime wiring**: `openagent.security.wire_default_scanner()` is installed at Fusion init; curated/semantic memory writes go through regex baseline plus optional extra scanner hook. This is defense-in-depth, not a prompt-injection guarantee.
- **FTS single-CJK query tokens**: `fts_query` keeps single CJK/Hangul/Kana tokens for NEW-14.

### Still requires external infrastructure / operator action
- **mTLS**: terminate or enforce mTLS at ingress proxy/service mesh (Envoy/Nginx/Traefik/Istio). Repo provides hooks/config docs only; do not claim in-repo mTLS without environment cert management.
- **TLS termination**: run behind TLS-terminating reverse proxy/load balancer; bind OpenAgent to private interface/loopback.
- **Distributed/shared rate limiting**: replace/process-augment `_RateLimiter` with Redis/API gateway/WAF rate limits for multi-instance deployments.
- **External WORM/tamper-proof audit**: forward `logs/ingress.jsonl` and audit records to append-only/WORM storage (e.g., S3 Object Lock, immutability-configured log sink). In-repo hash chain detects local tampering but is not WORM.
- **Full slowloris/header abuse protection**: enforce at reverse proxy (request/header/body timeouts, max header size/count, connection limits).
- **Prompt injection immunity**: not guaranteeable. Keep regex + pluggable scanner + memory context boundaries + owner-only sensitive tool rules; evaluate with adversarial corpus and external model/classifier if needed.
