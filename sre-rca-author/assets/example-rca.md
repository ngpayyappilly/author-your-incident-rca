# RCA: Member Profile API errors after connection pool config change

## 1. Incident Metadata

| Field | Value |
|---|---|
| Incident ID | INC0098765 |
| Service(s) | member-profile-api |
| Severity | P2 |
| Impact Start (UTC) | 2026-09-22T14:07:00Z |
| Detected (UTC) | 2026-09-22T14:19:00Z |
| Acknowledged (UTC) | 2026-09-22T14:23:00Z |
| Mitigated (UTC) | 2026-09-22T14:51:00Z |
| Resolved (UTC) | 2026-09-22T15:10:00Z |
| RCA Owner | Member Services SRE (fictional example) |
| Reviewers | Platform Engineering lead, Member Services service owner |
| Status | Draft |
| Draft Confidence | High |

## 2. Executive Summary

For 44 minutes on 22 September, 29% of member profile lookups failed, degrading sign-in and account pages. A Helm values change reduced the database connection pool on member-profile-api from 40 to 8 per pod and was synced to all 24 pods at once. Under normal traffic the smaller pool saturated, requests queued and timed out, and gateway retries then pushed request volume to 2.6x baseline. Nothing alerted on the error budget burn; a synthetic check fired 12 minutes after impact began. Recovery came from reverting the revision in Argo CD. The top actions are config validation with a canary stage, a gateway retry budget, and multi-window burn-rate alerting. This incident consumed about 29% of the 30-day error budget.

## 3. Impact Analysis

- **Member impact:** 29% of profile lookup requests returned 5xx or timed out between 14:07Z and 14:51Z, about 410,000 failed requests out of 1.41 million [E-001].
- **SLO impact:** SLI is request success rate with a 99.9% objective over 30 days. A 29% error rate for 44 minutes equals about 12.8 full-outage minutes, which is 29.5% of the 43.2-minute monthly error budget [E-001].
- **Business and operational impact:** Sign-in succeeded but account pages showed an error state for affected members; support contacts rose during the window [E-009].
- **Blast radius:** All regions served by the shared production cluster; no impact on the payments or search services, which do not call this API [E-004].

## 4. Incident Timeline

| Time (UTC) | Event | Source | Evidence |
|---|---|---|---|
| 2026-09-22T14:02:10Z | Argo CD syncs the new Helm values revision to all 24 pods; pods restart over about five minutes | Argo CD | [E-002] |
| 2026-09-22T14:07:00Z | Connection pool wait time rises and request errors begin as restarted pods take full traffic | Dynatrace | [E-003] |
| 2026-09-22T14:08:30Z | Gateway retries raise request volume to 2.6x baseline | Mesh metrics | [E-004] |
| 2026-09-22T14:19:10Z | Synthetic profile check alert fires and pages on-call | Synthetic monitoring | [E-005] |
| 2026-09-22T14:23:00Z | On-call engineer acknowledges and opens an incident channel | Chat transcript | [E-006] |
| 2026-09-22T14:41:00Z | Responders decide to revert the config revision after ruling out the database | Chat transcript | [E-006] |
| 2026-09-22T14:49:30Z | Argo CD syncs the previous revision | Argo CD | [E-007] |
| 2026-09-22T14:51:00Z | Success rate returns to baseline | Splunk Observability | [E-001] |
| 2026-09-22T15:10:00Z | Incident resolved after 19 minutes of stable metrics | Ticket record | [E-009] |

## 5. Technical Analysis

### 5.1 Root Cause Statement

**Root cause:** The service's connection pool size was tunable through a values file with no range validation, no load-test requirement, and no staged rollout, so a value too small for production concurrency could reach every pod at once [E-008].

**Trigger:** A values refactor changed `maxPoolSize` from 40 to 8 in the production overlay and Argo CD synced it to all pods [E-002].

### 5.2 Contributing Factors

- **CF-1 No validation or staged rollout for runtime config:** CI accepted any integer for the pool size and the sync updated all pods together, so the defect had full blast radius immediately [E-008].
- **CF-2 Gateway retries without a budget:** The mesh route retried each failed request up to 3 times, which multiplied load on an already saturated service and prolonged queueing [E-004].
- **CF-3 No burn-rate alerting:** No alert evaluated SLI burn; detection depended on a synthetic check and took 12 minutes [E-005].
- **CF-4 Slow rollback decision and path:** Responders spent 18 minutes ruling out the database before reverting, and the revert required a manual Argo CD sync [E-006].

### 5.3 Bottleneck Analysis

The first hop to deviate from baseline was the service's own database connection pool: wait time at p99 rose from 3 ms to 1.9 s and pool usage sat at 8 of 8 on every pod from 14:07Z [E-003]. The database itself was not saturated, with connections at 22% of its maximum throughout [E-010]. Request volume to the service rose 2.6x because the gateway retried timeouts, which kept the pools full even as members retried in the client [E-004].

### 5.4 Five Whys

1. Why did members see errors? Profile requests timed out waiting for a database connection from the pool [E-003].
2. Why were connections unavailable? Each pod's pool was 8, down from 40, and concurrency per pod exceeded 8 at normal load [E-003].
3. Why was the pool reduced to 8? A values refactor changed the production overlay and the number was not caught in review [E-008].
4. Why was it not caught before production? CI had no range check and policy did not require a load test or canary for config-only changes [E-008].
5. Why did it take 12 minutes to detect and 32 to mitigate? Alerting had no burn-rate signal and rollback depended on a manual sync after a lengthy database investigation [E-005] [E-006].

### 5.5 Hypotheses Considered

| ID | Hypothesis | Supporting evidence | Contradicting evidence | Verdict |
|---|---|---|---|---|
| H-1 | Pool size reduction exhausted connections | [E-003] [E-002] | None; revert removed the symptom within 90 seconds [E-007] | Confirmed |
| H-2 | Database saturation or failover | Initial alert pattern resembled past DB incidents [E-006] | DB connections at 22% of max and latency flat [E-010] | Ruled out |
| H-3 | Traffic spike from a campaign | Request volume rose 2.6x [E-004] | Volume rise began after errors and matched retry multiplier, not external traffic [E-004] | Ruled out |

## 6. Detection and Response Analysis

- **TTD / TTA / TTM / TTR:** 12 min / 4 min / 32 min / 63 min, computed from the metadata timestamps.
- **How we found out:** A synthetic profile check paged on-call at 14:19Z; no SLI-based alert fired [E-005].
- **Detection gap:** The service has an availability SLO but no burn-rate alert, so a 29% error rate was only caught by an external check [E-005].
- **Response effectiveness:** The on-call acknowledged within 4 minutes. The revert decision was delayed by a database investigation because no runbook linked recent config changes to pool symptoms [E-006].
- **What went well:** The previous revision was intact in Git and the revert took under two minutes once decided [E-007].
- **What went poorly:** The change was not surfaced in the incident channel until 14:38Z, although the sync event was visible in Argo CD from 14:02Z [E-006].
- **Where we got lucky:** The change landed mid-morning with an on-call already online; the same change during a peak traffic window would have burned the budget faster [E-001].

## 7. Action Items

| ID | Action | Type | Addresses | Owner | Priority | Due | Tracking |
|---|---|---|---|---|---|---|---|
| A-1 | Add schema and range validation for pool settings in CI, and add a 10% canary stage that fails the Argo CD rollout when 5xx exceeds 1% for 5 minutes | Prevent | CF-1 | Platform Engineering | P0 | 2026-10-30 | ADO-4412 |
| A-2 | Cap mesh retries at 1 attempt with a retry budget of 10% of active requests on the member-profile route | Prevent | CF-2 | Platform Engineering | P0 | 2026-10-16 | ADO-4413 |
| A-3 | Add multi-window burn-rate alerts (1h/5m at 14.4x and 6h/30m at 6x) for the profile availability SLI, routed to Member Services on-call | Detect | CF-3 | Member Services SRE | P0 | 2026-10-14 | ADO-4414 |
| A-4 | Add a runbook step that checks Argo CD sync events in the prior 24 hours and automate rollback on canary failure | Mitigate | CF-4 | Member Services SRE | P1 | 2026-11-13 | ADO-4415 |
| A-5 | Add load shedding at pool saturation so excess requests fail fast with 429 and the service stays within its queue limit | Mitigate | CF-2 | Member Services engineering | P1 | 2026-11-20 | ADO-4416 |

**Accepted risks:** None

## 8. Security Review

No security impact identified: access logs and audit events for the window show no unauthorized access, and no credentials or data were exposed [E-009].

## 9. SRE Reliability Principles Review

| Principle | Assessment |
|---|---|
| SLO and error budget | SLO existed; 29.5% of the monthly budget burned in one incident, so the budget policy should trigger a review of config-change safety before further risky rollouts |
| Monitoring (symptom-based alerting) | Gap: no burn-rate alerts; detection relied on a synthetic check |
| Release engineering and rollout safety | Gap: config-only changes bypassed canary and load testing; all pods updated together |
| Capacity and load | Pool capacity was never sized from measured concurrency; add sizing guidance to the service profile |
| Graceful degradation and dependency handling | Gap: unbounded gateway retries and no load shedding |
| Toil and automation | Manual Argo CD revert and manual change lookup slowed response |
| Incident response and communication | Roles were assigned quickly; change visibility in the channel was late |
| Learning and follow-through | Two prior RCAs this year cited config rollout safety; closure of those actions should be reviewed alongside A-1 |

## 10. Appendix and Sign-Off

### 10.1 Evidence Ledger

| ID | Source | Query / Link | Time Range | Key Finding | Collected (UTC) |
|---|---|---|---|---|---|
| E-001 | Splunk Observability | member-profile-api success ratio, 1m, vs prior week | 2026-09-22T13:00Z-16:00Z | Success rate 71% during impact vs 99.96% baseline; recovered 14:51Z | 2026-09-23T09:10:00Z |
| E-002 | Argo CD | Application sync history, member-profile-api | 2026-09-22T13:30Z-14:30Z | Revision synced 14:02:10Z; diff shows maxPoolSize 40 to 8 | 2026-09-23T09:14:00Z |
| E-003 | Dynatrace | DB pool wait time and in-use, per pod | 2026-09-22T13:00Z-16:00Z | Pool wait p99 3 ms to 1.9 s; in-use 8/8 on all pods from 14:07Z | 2026-09-23T09:20:00Z |
| E-004 | Mesh metrics and VirtualService | Request rate to service; route retry config | 2026-09-22T13:00Z-16:00Z | Retries attempts: 3; request rate 2.6x baseline from 14:08Z | 2026-09-23T09:26:00Z |
| E-005 | Synthetic monitoring and alert history | Alert firing log, profile check | 2026-09-22T13:30Z-15:30Z | Synthetic alert 14:19:10Z; no SLI burn alert exists | 2026-09-23T09:31:00Z |
| E-006 | Incident channel transcript | Export of INC0098765 channel | 2026-09-22T14:19Z-15:15Z | Ack 14:23Z; DB investigation; revert decision 14:41Z; change surfaced 14:38Z | 2026-09-23T09:40:00Z |
| E-007 | Argo CD | Rollback sync event | 2026-09-22T14:40Z-15:00Z | Previous revision synced 14:49:30Z; errors cleared by 14:51Z | 2026-09-23T09:44:00Z |
| E-008 | Git and CI | PR review record and pipeline run for the values change | 2026-09-21T00:00Z-2026-09-22T14:00Z | Reviewed without load test; CI has no range check for pool size | 2026-09-23T09:50:00Z |
| E-009 | Ticket system | INC0098765 record and access audit query | 2026-09-22T14:00Z-15:30Z | Support contacts up; audit shows no unauthorized access | 2026-09-23T09:55:00Z |
| E-010 | Database metrics | Connections and query latency | 2026-09-22T13:00Z-16:00Z | Connections 22% of max; query latency flat | 2026-09-23T10:00:00Z |

### 10.2 Open Questions

- Intent behind the pool size change (unit or tuning error) is unconfirmed; the PR author should clarify [UNVERIFIED].
- Support contact volume figure came from the ticket record and was not cross-checked against the contact-center system [UNVERIFIED].

### 10.3 Sign-Off

| Role | Name | Decision | Date |
|---|---|---|---|
| RCA Owner | | Pending | |
| Service Owner | | Pending | |
| SRE Reviewer | | Pending | |
