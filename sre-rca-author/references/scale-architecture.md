# Scale Architecture

How to run this skill over tens or hundreds of incidents without losing quality or burning money.

Contents: 1. Batch shape · 2. Service profile cache · 3. Depth tiers and budgets · 4. Isolation and failure handling · 5. Fleet metrics · 6. Triggering patterns · 7. Rollout phases

## 1. Batch shape

```
manifest (incident list + intake fields)
   │
   ▼
planner ── groups incidents by service, assigns depth tier, orders by severity
   │
   ├── profile builder (once per service, cached)
   │
   ▼
per-incident worker (isolated context)
   intake → evidence → timeline → analysis → draft → validate/repair → handoff
   │
   ▼
output store: rca.md, evidence/, report.json, handoff.md
   │
   ▼
aggregator: fleet metrics, cross-incident patterns, review queue
```

The manifest is a list of intake objects (see `assets/intake_template.yaml`). Workers are independent; run them in parallel up to the rate limits of your observability and ticketing APIs, which are the real constraint, not model throughput.

## 2. Service profile cache

A service is learned once, reused across every incident that touches it. Store at `service-profiles/<service>.md` with front matter:

```yaml
service: checkout-api
built_at: 2026-10-01
sources: [catalog, gitops, slo-defs, prior-rcas]
architecture_marker: <git sha or catalog revision>
```

Invalidate when older than 30 days or when the architecture marker changes. A worker may append a `## Learned during INC-...` note, but only the profile builder rewrites the file, which keeps concurrent workers from corrupting it. This cache is the largest cost lever: profile building is the most query-heavy phase and is identical across incidents.

## 3. Depth tiers and budgets

| Tier | Applies to | Evidence | Analysis | Output |
|---|---|---|---|---|
| Full | P1, repeat incidents, customer-visible SLO breach | Full change scan, traces, dependency cross-check, baseline week | ≥3 hypotheses, branching Five Whys | All 10 sections |
| Standard | P2 | Golden signals, change scan, logs | ≥2 hypotheses, single Five Whys chain | All 10 sections, shorter |
| Lite | P3, near-misses | Alerts, change scan, one log query | Primary hypothesis, ruled-out list optional | Sections 1-7, others marked "Not assessed (Lite)" |

Set a per-incident budget (query count, wall-clock, tokens) per tier. When the budget is hit, finish the draft with what exists, lower Draft Confidence, and list the gaps in Open Questions. A bounded, honest draft beats an unbounded one.

Note: the validator's required sections apply to Full and Standard. For Lite, run with `--tier lite`.

## 4. Isolation and failure handling

- One context per incident. Never carry one incident's evidence into another's; cross-incident insight happens in the aggregator.
- Idempotent: re-running an incident overwrites its own output directory only.
- Failure of one worker (API outage, empty data) records a `failed` status with the reason and moves on.
- Retries with backoff and jitter against rate-limited APIs; cap total retries per incident.
- Read-only credentials only. The agent never needs write access during investigation; action-item creation, if automated, is a separate, explicitly approved step.

## 5. Fleet metrics (treat the agent as a production service)

Define SLIs and review them monthly; these tell you whether the agent is helping:

| Metric | Meaning | Target example |
|---|---|---|
| Validator pass rate (first draft) | Draft quality before repair | >85% |
| Evidence coverage | Share of claims with citations | >90% |
| Owner edit ratio | Share of text the owner rewrote before sign-off | <30% and falling |
| Root-cause reversal rate | Owner or panel replaced the agent's root cause | <10% |
| Time to first draft | Incident resolved → draft ready | <1h for P1 |
| Action item closure rate | Actions closed by due date | Track, compare to pre-agent baseline |
| Cost per RCA | Tokens + API calls by tier | Track trend |

Sample 10% of drafts for human audit against the reviewer rubric in `quality-and-blameless.md`; feed misses back into this skill's references. Keep a golden set of past incidents with known root causes and re-run it whenever the skill changes.

## 6. Triggering patterns

- **On resolve:** a ticket-system rule fires when a P1/P2 moves to Resolved, enqueueing the incident with its intake fields.
- **Scheduled sweep:** weekly job drafts RCAs for resolved incidents lacking one.
- **On demand:** the owner invokes the skill for one incident and answers the batched intake question.

Always notify the owner when a draft is ready; a draft nobody knows about is not an RCA.

## 7. Rollout phases

1. **Shadow:** drafts generated for past incidents with known RCAs; compare root causes and action items to the human versions.
2. **Assist:** drafts offered to owners on live incidents; owner edit ratio tracked.
3. **Default:** draft generated automatically for every P1/P2; owners review and sign off.
4. **Proactive:** aggregator surfaces recurring factors across incidents to the governance review.

Advance a phase only when its metrics hold for a full review cycle.
