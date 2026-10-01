# Historical benchmark results

The README reports the latest audited v5 results from the original native-product benchmark. This historical evaluation is separate from the public project's v1.0.0 scorer and application deployment.

## Comparison scope

Each product was evaluated on 21 Kubernetes fault scenarios. Edge Delta detected and investigated 18; native Grafana detected and investigated 12. Detection uses all 21 scenarios as its denominator. The shared-scenario mitigation comparison uses the 12 scenarios with investigations from both products.

| Measure | Native Edge Delta | Native Grafana |
|---|---:|---:|
| Scenarios detected | 18/21 (85.7%) | 12/21 (57.1%) |
| Supported final mitigation, shared investigated scenarios | 9/12 (75.0%) | 6/12 (50.0%) |
| Supported final mitigation, all investigated scenarios | 10/18 (55.6%) | 6/12 (50.0%) |
| Candidate proposal; essential details missing | 6/18 (33.3%) | 3/12 (25.0%) |
| Incorrect or unsafe final advice | 0/18 (0.0%) | 3/12 (25.0%) |
| No final proposal | 2/18 (11.1%) | 0/12 (0.0%) |

There were no partial or insufficient-final-evidence verdicts in these 30 investigations. Final-quality categories are mutually exclusive. The all-investigated comparison covers different scenario cohorts; the shared comparison controls for that difference but excludes scenarios detected by only one product.

## How the judgments were made

- **Judge:** GPT-6-Astra, high reasoning, with tools disabled; the same v5 rules applied to both products.
- **Scoring input:** the selected final report and next steps, earlier advice, available operational traces, and scenario implementation facts. Only explicitly referenced, separately captured PR scope was attached where eligible.
- **Supported mitigation:** a concrete causal correction or bounded containment, with no active incorrect or unsafe final advice. A proposal can qualify while approval, implementation or deployment verification remains. Missing essential causal, target or data-safety facts makes it a candidate.
- **Earlier advice:** evaluated separately from the final recommendation. Correcting an earlier mistake does not erase it from that separate assessment.
- **Review:** 30 validated judgments. Five fresh citation retries and two deterministic citation repairs were recorded. Three intermediate-advice cases received documented primary review; no final-quality verdict was overridden.

The historical runs occurred at different times. Referenced third-party PRs can clarify an adopted proposal; they do not establish independent authorship. The scores do not demonstrate that an investigator executed a repair or restored service.

The original transcript renderer shortened some tool outputs. Final-answer text was not shortened. Historical action-safety claims need review against complete captures, so they are not headline metrics here. A new rendering does not retroactively change the evidence supplied to an old judgment.

## Relation to this public project

These results describe the original evaluation. The public application and scorer have evolved separately; running this release does not automatically reproduce the historical table. A comparison claiming to use the public rubric requires grading both products under that rubric with matching scenario facts and the same evidence-selection rules.

The two historical OOM cases used to test the public HTTP scorer are workflow checks, not a replacement benchmark cohort. They are excluded from the table above.

## Source snapshot

The table was copied from the parent benchmark's audited `native-final-quality-v5` report. The original judgments and earlier scorer versions remain unchanged in the parent project. The report hash below identifies the exact source used; it does not substitute for releasing the underlying evidence.

- Source report SHA-256: `e18de2955ce498913aa116569abb6eedfafaf412b81afd9bd3ad036ba39c5864`
- Frozen input index SHA-256: `88189027497328e82902c667c105b795552934b28586ab6247e3e1961a7a8f67`
- Audit SHA-256: `8cf6c3d4ffc80bf7ef3dc72f3e87daca364b52908b187a06bef455c3907c375f`
