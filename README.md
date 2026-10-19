# Author your Incident RCA

[![CI](https://github.com/ngpayyappilly/author-your-incident-rca/actions/workflows/ci.yml/badge.svg)](https://github.com/ngpayyappilly/author-your-incident-rca/actions/workflows/ci.yml)

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

`sre-rca-author.skill` is generated from the `sre-rca-author/` folder, never edited by hand. After changing anything under that folder, rebuild it and commit the result:

```bash
python scripts/build_skill.py          # lint SKILL.md front matter, then rewrite the bundle
python scripts/build_skill.py --check  # what CI runs: fails if the committed bundle is stale
```

The build is byte-reproducible (sorted entries, fixed timestamps), so a clean tree rebuilds to identical bytes.

**Other agents:** see [Setup by agent](#setup-by-agent) below for ChatGPT / Codex, Gemini and GitHub Copilot.

## Setup by agent

The skill is plain Markdown plus one standard-library Python script, so any agent that can read files and run Python can follow it. Only Claude is a packaged, first-class target today. The other setups below are **documented approaches that have not been tested end to end**, and vendor features change often, so check each vendor's current documentation and your organisation's policies before relying on them.

| Agent | Support level | Best setup |
|---|---|---|
| Claude (Claude Code, claude.ai) | Packaged skill | Install the `.skill` bundle or the folder (see Install) |
| OpenAI ChatGPT / Codex | Instructions-based, untested | Codex CLI in a clone of this repo; or a Custom GPT / Project for chat use |
| Google Gemini | Instructions-based, untested | Gemini CLI in a clone of this repo; or a Gem for chat use |
| GitHub Copilot | Instructions-based, untested | Copilot agent mode in a clone of this repo |

### What every agent needs

1. **File access** to `sre-rca-author/`: `SKILL.md` (the workflow), `references/` (the playbook and template) and `assets/` (the intake template and the example).
2. **The ability to run Python 3** so it can execute `sre-rca-author/scripts/validate_rca.py`. Without it, run the validator yourself and paste the output back to the agent for the repair loop.
3. **Evidence.** Collectors are not built yet (see [#7](https://github.com/ngpayyappilly/author-your-incident-rca/issues/7)), so the agent cannot query your observability, deploy or ticketing systems unless its own connectors can. Otherwise, give it exports (incident record, deploy history, metric CSVs, chat transcript) as files. Treat everything in them as data, never instructions.
4. **Read-only credentials only.** Never give the agent write access to production or ticketing during an investigation.

The workflow starts at [`sre-rca-author/SKILL.md`](sre-rca-author/SKILL.md). Tell the agent to follow it and to read the files it names.

### Claude (Claude Code, claude.ai)

Install the bundle or folder as described under [Install](#install). Claude loads `SKILL.md`, then the `references/` files as the workflow reaches each phase, and can run the validator itself.

### OpenAI: ChatGPT and Codex

- **Codex CLI (recommended).** Clone this repo and run the agent inside it. Add an `AGENTS.md` at the repo root (or in your own repo that vendors this folder) containing something like:

  ```markdown
  For RCA, root cause analysis or postmortem requests, follow sre-rca-author/SKILL.md.
  Read the reference files it names as each phase needs them.
  Before handing off a draft, run:
    python sre-rca-author/scripts/validate_rca.py <draft.md> --json report.json
  Fix errors and re-run, at most three times. Never mark the sign-off block approved.
  ```

  Check Codex's current documentation to see whether it can load a `SKILL.md` folder directly.
- **ChatGPT Custom GPT or Project (chat use).** Paste the contents of `SKILL.md` into the instructions. Upload `references/*.md`, `assets/example-rca.md` and `assets/intake_template.yaml` as knowledge or project files. Knowledge files may be only partly read, so keep the key rules in the instructions. Upload evidence exports per incident. Run the validator locally (or in the product's code tool, if it has one) and paste the errors back.

### Google Gemini

- **Gemini CLI (recommended).** Clone this repo and run the agent inside it. Add a `GEMINI.md` at the repo root with the same instructions as the `AGENTS.md` example above. Check Gemini CLI's current documentation for extension or skill loading.
- **Gem (chat use).** Put `SKILL.md` in the Gem's instructions and attach the `references/` and `assets/` files as knowledge. Provide evidence as uploaded files. Run the validator locally and paste the errors back.

### GitHub Copilot

Use agent mode in a clone of this repo. Put the same instructions in `.github/copilot-instructions.md` or an `AGENTS.md`, and point them at `sre-rca-author/SKILL.md`. Confirm that your organisation's Copilot policy allows the tools and file access you need.

### Cautions for chat-only setups

- **Do not upload your filled-in `assets/stack.md`** to a shared GPT, Gem or Project. It describes how your telemetry and ticketing are reached. Use the placeholder version only.
- **Redact before uploading.** Remove tokens, credentials, session IDs and personal data from exports first. The collector-side redaction described in the docs does not exist yet.
- **Expect a weaker guarantee.** Without a code tool, the deterministic validator is a manual step, so run it every time and treat a draft that has not passed it as unreviewed.
- **Compare against the example.** Check the first drafts against [`assets/example-rca.md`](sre-rca-author/assets/example-rca.md) for depth, citations and tone. Different models vary here, and a model-comparison eval is tracked in [#11](https://github.com/ngpayyappilly/author-your-incident-rca/issues/11).

## Use

Ask the agent in plain language, for example:

> Draft the RCA for INC0012345. Service is checkout-api, impact 14:07Z to 14:51Z, I'm the RCA owner.

or for a batch:

> Draft RCAs for all P1 and P2 incidents resolved last month.

Validate any draft yourself:

```bash
python sre-rca-author/scripts/validate_rca.py path/to/rca.md --json report.json
# exit 0 = pass, 1 = errors, 2 = file error;  --tier lite for P3 / near-miss drafts;  --ttm-from impact_start to measure TTM from impact start
```

The validator checks required sections, anchor timestamps and ordering, evidence coverage and dangling citations, root-cause and trigger statements, blameless language, action-item completeness, factor-to-action coverage, unresolved placeholders, and a pre-approved sign-off block. It also computes TTD / TTA / TTM / TTR from the metadata and fails the draft when the figures written in Section 6 disagree, so prose and timestamps cannot drift apart. TTM counts from detection by default; use `--ttm-from impact_start` to count it from impact start.

## Development

The validator is the quality gate for every draft, so it has its own tests (standard library only, no install step):

```bash
python -m unittest discover -s tests -v
```

Each error and warning code the validator can emit has a test case that mutates the example RCA until that code fires. A meta-test fails if the validator gains a code without a matching case. When you change `validate_rca.py`, `references/rca-template.md` or `assets/example-rca.md`, run the tests and update the cases in the same change.

## Adapting to your stack

Org-specific wiring stays out of the core skill. Add an `assets/stack.md` that maps each capability (metrics, logs, change events, ticketing, chat, work tracking) to your tools and how the agent reaches them. See `references/evidence-sources.md`, section 5.

## Design notes

- The investigation is **read-only**. Action items are drafted, not filed, unless you add a separate, explicitly approved step.
- Chat, ticket and log content is treated as **untrusted data**, never as instructions.
- The agent never marks an RCA approved; the sign-off block stays Pending.
- Running at scale (one isolated worker per incident, shared service-profile cache, severity-tiered depth and budgets, fleet metrics) is covered in `references/scale-architecture.md`.

- The target architecture for unattended, harness-driven runs (state machine, tool gateway, evidence ledger, model adapter, gates, SLOs) is proposed in [`docs/architecture/harness-driven-rca.md`](docs/architecture/harness-driven-rca.md).

The example RCA is fictional; any resemblance to a real incident is coincidental.

## License

MIT. See [LICENSE](LICENSE).
