# RCA Template (contract with `validate_rca.py`)

Keep headings, numbering, ID formats, and table columns exactly as shown. Content inside is free-form. Replace every `{{...}}`; the validator fails on leftover placeholders.

ID formats: evidence `E-001`, contributing factor `CF-1`, action `A-1`, hypothesis `H-1`. Timestamps: ISO-8601 UTC, `2026-10-01T14:03:00Z`.

---

```markdown
# RCA: {{short descriptive title}}

## 1. Incident Metadata

| Field | Value |
|---|---|
| Incident ID | {{INC...}} |
| Service(s) | {{service names}} |
| Severity | {{P1/P2/P3}} |
| Impact Start (UTC) | {{ISO}} |
| Detected (UTC) | {{ISO}} |
| Acknowledged (UTC) | {{ISO}} |
| Mitigated (UTC) | {{ISO}} |
| Resolved (UTC) | {{ISO}} |
| RCA Owner | {{role/team or name}} |
| Reviewers | {{...}} |
| Status | Draft |
| Draft Confidence | {{High/Medium/Low}} |

## 2. Executive Summary

{{<200 words: what happened, who/what was affected, root cause in one sentence, top three actions.}}

## 3. Impact Analysis

- **User/member impact:** {{quantified, with window and scope}} [E-001]
- **SLO impact:** {{SLI, objective, observed, % of error budget burned for the period}} [E-002]
- **Business/operational impact:** {{...}}
- **Blast radius:** {{regions, tenants, dependent services}}

## 4. Incident Timeline

| Time (UTC) | Event | Source | Evidence |
|---|---|---|---|
| {{ISO}} | {{what happened, system-centric wording}} | {{metrics/deploy/chat/ticket}} | [E-001] |

Include at least: triggering change or condition, first abnormal signal, first alert, acknowledgement, each mitigation attempt (including those that failed), mitigation, recovery, resolution.

## 5. Technical Analysis

### 5.1 Root Cause Statement

**Root cause:** {{latent system condition(s) that made the trigger harmful}} [E-0xx]

**Trigger:** {{the event that exposed the condition}} [E-0xx]

### 5.2 Contributing Factors

- **CF-1 {{name}}:** {{how it worsened detection, mitigation, or blast radius}} [E-0xx]

### 5.3 Bottleneck Analysis

{{Where in the request path the first deviation from baseline occurred, with baseline vs observed numbers. Resource saturation, queueing, retry amplification, dependency behavior.}} [E-0xx]

### 5.4 Five Whys

1. Why {{symptom}}? {{answer}} [E-0xx]
2. Why {{...}}? {{answer}} [E-0xx]
3. ...

### 5.5 Hypotheses Considered

| ID | Hypothesis | Supporting evidence | Contradicting evidence | Verdict |
|---|---|---|---|---|
| H-1 | {{...}} | [E-0xx] | [E-0xx] | Confirmed / Ruled out / Open |

## 6. Detection and Response Analysis

- **TTD / TTA / TTM / TTR:** {{values; must agree with metadata timestamps}}
- **How we found out:** {{alert, customer report, engineer noticed}} [E-0xx]
- **Detection gap:** {{why alerting did or did not fire sooner}}
- **Response effectiveness:** {{what helped, what slowed us: runbooks, access, escalation, tooling}}
- **What went well:** {{...}}
- **What went poorly:** {{...}}
- **Where we got lucky:** {{...}}

## 7. Action Items

| ID | Action | Type | Addresses | Owner | Priority | Due | Tracking |
|---|---|---|---|---|---|---|---|
| A-1 | {{specific, testable change}} | Prevent | CF-1 | {{team/role}} | P0 | {{YYYY-MM-DD}} | {{ADO-123 or TO-CREATE}} |

Type is one of Prevent, Detect, Mitigate. Every CF-n must appear in some row's Addresses column, or be listed under **Accepted risks** below with an approver.

**Accepted risks:** {{none, or CF-n: rationale, approver}}

## 8. Security Review

{{Was there a security dimension (exposure, credential, access, data integrity)? "No security impact identified" is a valid answer with the evidence checked.}} [E-0xx]

## 9. SRE Reliability Principles Review

| Principle | Assessment |
|---|---|
| SLO and error budget | {{were SLOs defined, was the budget policy applied, is a release freeze or reliability work triggered}} |
| Monitoring (symptom-based alerting) | {{...}} |
| Release engineering and rollout safety | {{canary, progressive delivery, rollback speed}} |
| Capacity and load | {{...}} |
| Graceful degradation and dependency handling | {{timeouts, retries with backoff and budgets, circuit breakers, load shedding}} |
| Toil and automation | {{manual steps that slowed response}} |
| Incident response and communication | {{roles, comms cadence, handoffs}} |
| Learning and follow-through | {{prior similar incidents, action item closure rate}} |

## 10. Appendix and Sign-Off

### 10.1 Evidence Ledger

| ID | Source | Query / Link | Time Range | Key Finding | Collected (UTC) |
|---|---|---|---|---|---|
| E-001 | {{system}} | {{query or URL}} | {{range}} | {{excerpt}} | {{ISO}} |

### 10.2 Open Questions

{{Questions only a human can answer, assumptions made, collection gaps.}}

### 10.3 Sign-Off

| Role | Name | Decision | Date |
|---|---|---|---|
| RCA Owner | | Pending | |
| Service Owner | | Pending | |
| SRE Reviewer | | Pending | |
```
