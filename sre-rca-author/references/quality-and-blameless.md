# Quality Rubric and Blameless Language

## Blameless principle

Google's postmortem practice assumes people acted reasonably on the information and tools they had. The question is never "who" but "what about our systems made this outcome possible, likely, or hard to detect". Blame also destroys the information supply: people stop reporting what they know.

Refer to roles ("the on-call engineer", "the deploying team"), never names, unless the person is a documented owner in an action item.

## Rewrites

| Avoid | Prefer |
|---|---|
| "Engineer X pushed a bad config" | "A config change to the rate-limit map was applied to all instances; the pipeline had no schema validation or staged rollout." |
| "Human error" | Describe the action, then the missing safeguard: "The manual step allowed an out-of-range value; no check rejected it." |
| "The team failed to notice the alert" | "The alert routed to a channel with no on-call owner; it was acknowledged 41 minutes after firing." |
| "Should have known / should have caught" | "Nothing in the review checklist or tests exercised this path." |
| "Careless", "negligent", "sloppy" | Delete the adjective; state the observable facts. |
| "Forgot to update the runbook" | "The runbook was not part of the change checklist, so it still described the old topology." |
| "Developer ignored the warning" | "The warning was non-blocking and shown alongside 200 similar warnings." |

## Evidence discipline

- Every factual sentence in sections 3-6 carries `[E-nnn]` or a tag.
- `[ASSUMPTION]` = a reasoned guess to be confirmed. `[UNVERIFIED]` = a claim from a human or document you could not check.
- A claim supported only by the owner's recollection is `[UNVERIFIED]` until a system record confirms it.
- Dangling citations (an ID not in the ledger) are errors. So are ledger rows no one cites; remove them or use them.

## Action item quality bar

A good action item passes all five:
1. **Specific:** names the component and the change.
2. **Testable:** you can tell when it is done and whether it works (an alert fires in a game day, a gate blocks a bad canary).
3. **Mapped:** addresses a named contributing factor.
4. **Owned:** a team or role accountable, with a due date and a tracking ID.
5. **Proportionate:** effort matches risk; low-value items are cut, not parked.

Weak to strong:
- "Improve monitoring" → "Add multi-window burn-rate alerts (1h/5m at 14.4x, 6h/30m at 6x) for checkout availability SLI, routed to the Payments on-call."
- "Be more careful with config" → "Add JSON-schema validation and a 10% canary stage to the config pipeline; fail the rollout on error-rate regression."
- "Review runbooks" → "Rewrite the cache-failover runbook for the multi-region topology and exercise it in the next game day."

## Reviewer rubric (for RCA owners and governance panels)

Score each 0-2; below 12/16 goes back for rework.

| Criterion | 0 | 2 |
|---|---|---|
| Root cause depth | Stops at the trigger or a person | Reaches changeable system conditions |
| Evidence | Narrative with no citations | Every claim cited; gaps declared |
| Timeline | Vague or single-source | UTC, multi-source, anchor times present |
| Impact | Adjectives | Quantified vs SLO with budget burn |
| Detection/response | Absent | Gaps analysed with TTD/TTA/TTM/TTR |
| Actions | Generic, unowned | Typed, mapped, owned, dated, tracked |
| Blamelessness | Individuals blamed | Systems and roles only |
| Learning | No luck/ruled-out/prior-incident review | Includes all three |
