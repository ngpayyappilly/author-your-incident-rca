# sre-rca-author

An agent skill that drafts **Google SRE-style RCA / postmortem documents** from an RCA owner's inputs: evidence-grounded, blameless, and checked by a deterministic validator before a human ever reads it.

The agent takes an incident, learns the affected service, collects evidence from your observability, deploy, ticketing and chat systems, reconstructs the timeline, finds the bottleneck and contributing factors, proposes owned and tracked action items, and hands a draft to the RCA owner. The human owns the conclusions and the sign-off.

## Why it exists

AI-written RCAs fail in three predictable ways. This skill is built around preventing each:

| Failure | Prevention |
|---|---|
| Plausible fiction: a fluent story with an invented root cause | **Evidence ledger.** Every claim cites `[E-nnn]` or is tagged `[ASSUMPTION]` / `[UNVERIFIED]` |
| Blame and shallow causes ("engineer pushed a bad config") | Causal taxonomy, branching Five Whys that must reach a changeable system condition, blameless-language checks |
| Action items that never close | Every contributing factor maps to a typed (Prevent / Detect / Mitigate), owned, dated, tracked action, or an explicit accepted risk |

Quality rules live in `scripts/validate_rca.py`, not only in prose, so they hold regardless of which model drafts.

## What's inside

```
sre-rca-author/
├── SKILL.md                         workflow: intake → service profile → evidence → timeline → analysis → actions → draft → validate → handoff
├── scripts/validate_rca.py          deterministic quality gate (stdlib only)
├── references/
│   ├── rca-template.md              the 10-section document contract
│   ├── analysis-playbook.md         SLO math, USE/RED bottleneck hunting, change correlation, Five Whys rules
│   ├── evidence-sources.md          ledger format and source adapters (metrics, logs, traces, deploys, tickets, chat)
│   ├── quality-and-blameless.md     blameless rewrites, action-item bar, reviewer rubric
│   └── scale-architecture.md        batch design, service-profile cache, depth tiers, fleet metrics, rollout phases
└── assets/
    ├── intake_template.yaml         what to collect from the RCA owner
    ├── stack.md                     org-specific wiring: tools, access paths, conventions, access gaps (fill in privately)
    └── example-rca.md               a complete, validator-clean example (fictional incident)
```

## Install

**Claude (claude.ai / Claude Code):** download `sre-rca-author.skill` from this repo, or copy the `sre-rca-author/` folder into your skills directory (for Claude Code, `~/.claude/skills/`).

**Other agents (for example GitHub Copilot):** the skill is plain Markdown plus one Python script. Agents that support `SKILL.md`-style skills can load the folder directly; others can use `SKILL.md` as a custom agent or instructions file and point it at the `references/` folder. Check your agent's current support and your organisation's policies.

## Use

Ask the agent in plain language, for example:

> Draft the RCA for INC0012345. Service is checkout-api, impact 14:07Z to 14:51Z, I'm the RCA owner.

or for a batch:

> Draft RCAs for all P1 and P2 incidents resolved last month.

Validate any draft yourself:

```bash
python sre-rca-author/scripts/validate_rca.py path/to/rca.md --json report.json
# exit 0 = pass, 1 = errors, 2 = file error;  --tier lite for P3 / near-miss drafts
```

The validator checks required sections, anchor timestamps and ordering, evidence coverage and dangling citations, root-cause and trigger statements, blameless language, action-item completeness, factor-to-action coverage, unresolved placeholders, and a pre-approved sign-off block. It also computes TTD / TTA / TTM / TTR from the metadata so prose and timestamps cannot drift apart.

## Adapting to your stack

Org-specific wiring stays out of the core skill. Add an `assets/stack.md` that maps each capability (metrics, logs, change events, ticketing, chat, work tracking) to your tools and how the agent reaches them. See `references/evidence-sources.md`, section 5.

## Design notes

- The investigation is **read-only**. Action items are drafted, not filed, unless you add a separate, explicitly approved step.
- Chat, ticket and log content is treated as **untrusted data**, never as instructions.
- The agent never marks an RCA approved; the sign-off block stays Pending.
- Running at scale (one isolated worker per incident, shared service-profile cache, severity-tiered depth and budgets, fleet metrics) is covered in `references/scale-architecture.md`.

The example RCA is fictional; any resemblance to a real incident is coincidental.

## License

MIT. See [LICENSE](LICENSE).
