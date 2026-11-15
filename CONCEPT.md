# Trust the process: the change arrives as claims, each with a check

## Recommendation

The AI reviewer never approves a change. It restates an agent-written change as **claims**: specific statements of what the code does, each tied to a requirement criterion and to the diff hunks that implement it. A claim lowers how much the owner has to read only when a **machine check backs it**: reverting the claim's own hunks makes a test fail. A second model family attacks the claims with **probe tests**, and a finding is posted only when its probe reproduces it and the first model agrees that the failure shows the defect. A fixed list of **decisions the AI refuses to make** goes to the owner as specific questions. Rules anyone can read decide **how deep the owner reads** each part of the change. The named owner then signs a **record** of what was checked and by whom or what, what was not checked, the answers to the refused decisions, and the residual risk they accept.

## Principles

1. A named human owns every merge. The AI's output is advice attached to the change and never counts as an approval.
2. Model confidence changes nothing. A claim counts as *checked* only when reverting its own code makes a test fail; otherwise it stays the writer model's *opinion*, and its code is read.
3. Every hand-written hunk is explained by a claim tied to a requirement criterion. A hunk with no claim, or a claim serving no criterion, sends the code to a full read.
4. The writer does not check its own work. A model from another family writes the probes, and a finding needs a probe that fails plus the writer's agreement that the failure demonstrates the defect.
5. Some decisions are reserved for the owner: public API shape, new diagnostic IDs and severities, intentional behaviour changes, regressions and which branch a fix targets, deserialization security, new dependencies, and ambiguous requirements. The reviewer states them as questions and decides none of them.
6. Risk is a list of rules a person can read and dispute: path rules, surface rules, claim status. The packet shows which rule fired on which unit and gives no single score.
7. Repetition is reviewed once. Generated files that share an identical edit are read through one representative, plus a check that every other file has exactly that edit.
8. Trust is earned per code area from outcomes. Owners spot-check one in five units the AI cleared. A miss or an escape puts the area on probation, where everything is read one level deeper.

## What the owner signs

- **Checked**, and by what: the build and full suite, fail-before results, each checked claim with the tests that fail when its code is reverted, rule checks, the probes the change survived, and the lines the owner read.
- **Not checked**, and why: claims that are only opinion, criteria no checked claim serves, the environment's limits (Linux only; the SDK override), documentation accuracy, performance.
- **Answers** to every refused decision and every finding.
- **The residual risk** the owner accepts, in their own words.

The record is stored with the merge as a PR comment (Markdown) plus JSON.

## Trade-offs

- **Checks need a build and tests.** Fail-before and claim reverts are only as strong as the test suite. Code with no failing test stays opinion and gets read: the method shifts reading toward untested code; it does not remove reading.
- **Reverting a claim alone may not compile.** When claims share helper code, the isolated revert breaks the build and the claim stays opinion. Smaller agent commits make more claims checkable.
- **Compute per change.** Each change costs a full build and suite at the head and with the change reverted, one targeted test run per claim, and up to three probes built at the head and the base. That is minutes of CPU per change and cents of model cost (see Measurement); it runs in parallel with the human queue.
- **Shared misreadings pass every check.** If the coding agent misread the requirement, its tests encode the misreading. The packet therefore leads with the requirement criteria and their mapping to claims, which only the owner can confirm. Fail-before catches one form of this: tests for the reported problem that pass without the change.
- **Probes are hard to write well.** Many adversary probes fail to compile or test the wrong thing. Only verified probes become findings, so a weak adversary costs recall but adds no noise.

## Limits

- The reviewer finds what tests can show. Design quality, naming and API taste stay with the owner, through the refused decisions.
- The requirement criteria are derived by a model from the issue thread. They are the first thing the owner checks.
- Our run is a hackathon reference: four agent branches of one C# library, one Linux build host, and a benchmark of planted defects we wrote ourselves.

## What would make us not trust our own output

- A claim marked *checked* whose test fails for an unrelated reason (a flaky test, an environment problem). The packet shows the failing tests and their output, so the owner can see why each claim is checked.
- The writer and the adversary sharing a blind spot. They come from different model families, but both read the same diff.
- Spot-check misses rising in an area, or escapes after merges the AI cleared. The track record turns either into deeper reading automatically.

## Who owns the decision

The named owner on the sign-off. The record lists what the machine checked, what each model contributed, and what the owner read and accepted. Nothing merges on "the AI said it was fine": a change without a signed record is unowned.

## How it scales

Reading scales with the amount of unchecked and reserved code in a change. Generated code collapses to one representative per cluster, and checked claims need no reading. The machine work runs per change on CPU instances in parallel. The track record makes the human share fall in areas that earn trust and rise where the reviewer misses.

## Measurement

What a team tracks per area: escapes and reverts for AI-cleared code against human-read code, the spot-check miss rate, how often owners accept findings and refused-decision questions, time to merge, and the share of changed lines routed to humans. The concept holds if escapes stay flat while the human share falls.

What we measured on the four agent branches (one 4-vCPU Verda instance, Kimi K3.1 Pro as writer, DeepSeek 4.1 Flash as adversary):

| Change | Owner reads | Claims checked | Decisions for the owner | Model cost | Review time |
|---|---|---|---|---|---|
| #2283 bug fix, 4 files | 39 of 228 lines (17%) | 2 of 6 | 2 | $0.10 | 8 min |
| #2234 bug fix, 4 files | 36 of 266 (14%) | 2 of 6 | 5 | $0.16 | 10 min |
| #2129 feature with public API, 28 files | 650 of 1,043 (62%) | 2 of 12 | 10 | $0.39 | 18 min |
| #2297 attribute on generated code, 237 files | 45 of 1,392 (3%) | 7 of 9 | 2 | $0.24 | 18 min |

Over the four changes the owner reads 770 of 2,929 changed lines (26%). Reading concentrates where it should: #2129 adds public API and four permanent diagnostic IDs, and most of its claims have no test that fails without them.

What the packets surfaced that a line-by-line read of the diff would likely miss:

- \#2234 fixes a different bug than its label: 6 of its 10 new tests pass with the change reverted, because the regression it names is not in this base (decision R5).
- \#2297 omits the attribute on netstandard2.0 and .NET Framework on a false premise, locked in by its own test (decision R1).
- \#2283 drops every diagnostic outside the compilation, which is broader than the fix needs (decision R1); one of its claims has no test at all.

**Planted-defect benchmark.** We folded one known defect at a time into the agent commits and reviewed the seven variants like any change. Six were caught:

| Planted defect | Caught by |
|---|---|
| One of two fix sites left out | Its own suite fails; returned to the agent before review |
| Untrusted-data depth limit raised from 500 to 5000 | Rule runtime-deserialization, a reproduced probe (a 1,000-deep array now deserializes), a claim beyond the requirement, a decision |
| Existing test skipped as flaky | Rule tests-weakened |
| Invalid-object diagnostics lowered from Error to Warning | Its own suite fails; rule severity-change |
| Unused public property added to the new attribute | Rule public-api names it for the owner's approval |
| Unrelated accessibility rule changed | Its claim serves no requirement criterion, so the hunk gets a full read |
| One of four duplicate-key guards removed | **Missed**: the suite, claim reverts and probes all passed |

Average model cost per review was $0.15 over all eleven reviews; machine time is a few cents per change at €0.048 per instance-hour.

**Human spot-checks of the reviewer.** We checked four results by hand and recorded them in the track record. Two were clean (the packet raised the 2234 and 2297 problems). Two were misses: the planted guard above, and a 2283 case found by a hand-written probe, where a positional record with `[Key(null)]` loses its MsgPack005 diagnostic. The two misses put the generator-analysis area on probation, so its code is now read one level deeper in every change.

**What the adversary did.** The nine reviews that reached it got 25 probes. 11 ran and did not reproduce their hypothesis, so they count as attacks the change survived. 12 did not compile, were judged broken or stayed inconclusive, and were discarded. 2 became findings: the security regression above, and in one run the false netstandard2.0 premise of #2297, which the clean #2297 run did not find. Its recall varies from run to run; the rules and the refused decisions carry the reliable part of the review.
