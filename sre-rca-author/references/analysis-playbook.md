# Analysis Playbook

Contents: 1. Impact and SLO math · 2. Finding the bottleneck · 3. Change correlation · 4. Causal taxonomy · 5. Five Whys rules · 6. Hypothesis discipline · 7. Common failure patterns · 8. Confidence levels

## 1. Impact and SLO math

- Use the service's own SLI definition. If none exists, say so (that is itself a contributing factor) and use request success rate and latency at the edge.
- Error budget burned = (bad events during incident) / (total allowed bad events in the SLO period). Show the arithmetic with the period (e.g. 30 days) and objective (e.g. 99.9%).
- Burn rate = observed error rate / allowed error rate. A burn rate of 14.4 sustained for 1h consumes 2% of a 30-day budget; use this to judge whether multi-window burn-rate alerts should have fired and when.
- Scope impact by dimension: region, tenant/member segment, endpoint, client version. "Partial" must be quantified or it is meaningless.

## 2. Finding the bottleneck

Walk the request path from the user inward and compare each hop to baseline. The first hop that deviates is where to dig; deviations further in may be effects.

**Service hops (RED / golden signals):** rate, errors, duration, saturation. Compare percentile latency (p50/p95/p99), not just means. Check error breakdown by status class and by dependency.

**Resources (USE):** for CPU, memory, disk I/O, network, file descriptors, threads, connection pools, queues: utilization, saturation (queue depth, throttling, run-queue, pending requests), errors. Saturation is the leading indicator; utilization alone hides it.

**Kubernetes and mesh specifics:** CPU throttling (cfs throttled periods), OOMKills and restarts, HPA lag and max-replica ceilings, pending pods and node pressure, PDB blocking drains, readiness probe flapping, DNS latency, Istio retry/timeout/outlier-detection settings, sidecar resource limits, connection-pool and circuit-breaker settings, NLB/LB target health and idle timeouts.

**Data tier:** connection exhaustion, lock contention, replication lag, slow-query regressions after a plan change, failover duration, cache hit-rate collapse.

**Dependencies:** compare your outbound call latency and errors with the dependency's own telemetry. If they disagree, suspect the network path, connection reuse, or client-side queueing.

Always state baseline vs observed with units and windows. "CPU high" is not a finding; "pod CPU throttled 38% of periods vs 2% baseline, from 14:05Z" is.

## 3. Change correlation

Enumerate every change in the lookback window: deploys and rollouts (GitOps sync events), Helm value changes, config and feature-flag flips, infra changes (Terraform apply, node pool, certificate rotation, DNS, mesh policy), dependency releases, traffic shifts (campaign, batch job, partner onboarding), and scheduled jobs.

For each, ask three questions and write the answers down:
1. **Timing:** does onset follow the change within the system's propagation delay?
2. **Scope:** does the blast radius match what the change touched?
3. **Mechanism:** can you describe, step by step, how this change produces these exact symptoms?

A change passing all three is a candidate trigger. Failing any one demotes it. Rollback or fix timing is strong confirming evidence: did symptoms resolve at the moment the change was reverted?

## 4. Causal taxonomy

Classify each factor so the action items cover the right layer. Prefer causes lower on this list (more systemic) over those higher up.

| Layer | Examples |
|---|---|
| Trigger | Deploy, config push, traffic spike, dependency failure, expiry |
| Latent defect | Unbounded queue, missing timeout, hard-coded limit, race, memory leak |
| Missing safeguard | No canary gate, no validation of config schema, no load shedding, no rate limit |
| Detection gap | Alert on cause not symptom, wrong threshold, missing SLI, alert routed to wrong team |
| Response gap | Stale runbook, unclear ownership, access delays, slow rollback path, comms confusion |
| Design/architecture | Shared fate, single region, retry amplification, tight coupling |
| Process/org | Review gaps, ownership gaps, error budget policy not enforced |

"Human error" is never a layer. When a person's action is in the chain, ask what made that action easy, likely, or invisible in its consequences, and put *that* in the layer table.

## 5. Five Whys rules

- Each answer must be evidenced or tagged.
- Branch when a why has multiple causes; number branches 3a, 3b.
- Stop at a changeable system, process, or design condition. If you reach "someone chose X", ask why X was a reasonable choice given what they could see, and continue.
- The chain should explain three things: why it happened, why it was not caught before release, and why it took as long as it did to detect and fix. Many RCAs only do the first.
- Five is a heuristic. Use as many as the evidence supports, not as many as the template suggests.

## 6. Hypothesis discipline

- Generate at least three hypotheses before testing any, including one you consider unlikely.
- For each, write a prediction that would be false if the hypothesis were wrong (e.g. "if it was the connection pool, errors should be concentrated on pods with >90% pool utilization").
- Seek disconfirming evidence first. A hypothesis that survives a real attempt to break it is worth more than one that collected agreeing screenshots.
- Record ruled-out hypotheses with the evidence that excluded them; reviewers and future responders will otherwise re-chase them.

## 7. Common failure patterns (checklist, not conclusions)

Retry storms and amplification (retries × layers), missing or mismatched timeouts across hops, thundering herd on restart or cache expiry, connection-pool or ephemeral-port exhaustion, queue buildup with no backpressure, config rolled to all instances at once, canary that did not exercise the failing path, health checks that do not reflect dependency health, autoscaler too slow for the burst, certificate or credential expiry, DNS TTL and negative caching, clock skew, noisy neighbor on shared nodes, quota and rate-limit ceilings at cloud or SaaS providers, log or metric pipeline saturation hiding the incident itself, failover that was never exercised.

Use as prompts for investigation. Never cite a pattern in the RCA without evidence from this incident.

## 8. Confidence levels

- **High:** a mechanism is demonstrated, timing matches, and the fix or rollback removed the symptom; alternatives are excluded by evidence.
- **Medium:** mechanism plausible, timing and scope consistent, but not directly demonstrated or alternatives only partly excluded.
- **Low:** correlation only, or evidence gaps (retention expired, no instrumentation). State the experiment or data that would raise confidence.

Draft Confidence in the metadata is the lowest confidence among the root-cause claims.
