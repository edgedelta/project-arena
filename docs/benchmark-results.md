# Benchmark results

We compared native Edge Delta, native Grafana, Claude + edx, and Claude + gcx across 21 Kubernetes incident scenarios. The tables evaluate 72 completed investigations: 18 native Edge Delta, 12 native Grafana, and 21 for each Claude configuration. Every column uses the same [scoring rubric](scoring-rubric-v1.0.0.md) and judge settings.

This page shows detection, diagnosis and final recommendation results. Action-safety and intermediate-advice scores remain separate in the complete scoring reports and are not displayed here.

## How investigations started

| Configuration | Start condition | Completed investigations |
|:---|:---|---:|
| Edge Delta native | Its monitors or scheduled loops detected an incident and opened an investigation. | 18/21 |
| Grafana native | Its alert rules triggered a native investigation. | 12/21 |
| Claude + edx | Externally started from 16 alerts and 5 customer reports. | 21/21 |
| Claude + gcx | Externally started from 12 alerts and 9 customer reports. | 21/21 |

The Claude columns measure investigation quality after a prompt was supplied. They do **not** measure independent detection, so detection is shown as **—**, not 21/21. The Claude runs used the same recorded model (`us.anthropic.claude-fable-5-1` through Bedrock), read-only observability access through edx or gcx, read-only Kubernetes access, and repository-scoped GitHub access for proposing changes. These conditions differ from the native products’ automatic investigation paths.

## All investigated scenarios

| Metric | Edge Delta native | Grafana native | Claude + edx | Claude + gcx |
| :--- | :---: | :---: | :---: | :---: |
| Detection | 18/21 (85.7%) | 12/21 (57.1%) | — | — |
| Root cause analysis | 15/18 (83.3%) | 9/12 (75.0%) | 18/21 (85.7%) | 19/21 (90.5%) |
| Blast radius | 12/18 (66.7%) | 8/12 (66.7%) | 18/21 (85.7%) | 18/21 (85.7%) |
| Final mitigation | 8/18 (44.4%) | 5/12 (41.7%) | 16/21 (76.2%) | 15/21 (71.4%) |
| Implementation readiness | 9/16 (56.2%) | 5/12 (41.7%) | 16/21 (76.2%) | 15/21 (71.4%) |

Detection uses all 21 scenarios for each native product. Diagnosis and final mitigation use every completed investigation in that column: 18, 12, 21 and 21 respectively. Implementation readiness excludes two Edge Delta investigations with no mitigation proposal, giving its denominator of 16. The different scenario cohorts make the matched comparison below useful as well.

## Comparison on the same 12 incidents

These are the incident types with an investigation from both native products, plus their corresponding Claude investigations. Detection is 100% for the native columns in this subset by construction; it does not replace the full 21-scenario detection result. Claude detection remains unmeasured.

| Metric | Edge Delta native | Grafana native | Claude + edx | Claude + gcx |
| :--- | :---: | :---: | :---: | :---: |
| Detection | 12/12 (100.0%) | 12/12 (100.0%) | — | — |
| Root cause analysis | 11/12 (91.7%) | 9/12 (75.0%) | 10/12 (83.3%) | 10/12 (83.3%) |
| Blast radius | 9/12 (75.0%) | 8/12 (66.7%) | 10/12 (83.3%) | 10/12 (83.3%) |
| Final mitigation | 7/12 (58.3%) | 5/12 (41.7%) | 8/12 (66.7%) | 8/12 (66.7%) |
| Implementation readiness | 8/12 (66.7%) | 5/12 (41.7%) | 8/12 (66.7%) | 8/12 (66.7%) |

Each platform was tested in a separate run. The matched table controls scenario inclusion, not launch prompts, execution times or investigation histories. In particular, an externally prompted Claude investigation is not evidence that Claude detected that incident itself.

## Final mitigation breakdown

| Final mitigation | Edge Delta native | Grafana native | Claude + edx | Claude + gcx |
| :--- | :---: | :---: | :---: | :---: |
| supported | 8/18 (44.4%) | 5/12 (41.7%) | 16/21 (76.2%) | 15/21 (71.4%) |
| partial | 1/18 (5.6%) | 0/12 (0.0%) | 0/21 (0.0%) | 0/21 (0.0%) |
| candidate | 7/18 (38.9%) | 5/12 (41.7%) | 0/21 (0.0%) | 0/21 (0.0%) |
| incorrect_or_unsafe | 0/18 (0.0%) | 2/12 (16.7%) | 5/21 (23.8%) | 6/21 (28.6%) |
| none | 2/18 (11.1%) | 0/12 (0.0%) | 0/21 (0.0%) | 0/21 (0.0%) |
| insufficient_final_evidence | 0/18 (0.0%) | 0/12 (0.0%) | 0/21 (0.0%) | 0/21 (0.0%) |

A supported proposal specifies a causal fix or bounded containment without active incorrect or unsafe final advice. A partial proposal covers only part of the incident. A candidate still needs an essential causal, target or safety decision. Implementation readiness is separate: a correction can be supported while an implementation detail remains unresolved.

Only the selected final report earns final mitigation credit. Earlier mistakes do not fail a corrected final recommendation. Proposals, approvals and PRs do not establish that a repair was executed or that service recovered.

## Method and evidence

- **Judge:** GPT-6-Astra through OpenRouter, high reasoning, maximum output 16,384 tokens, tools disabled. All four columns use identical settings and rubric text.
- **Final-answer selection:** native products use their recorded final report; Claude uses the harness-recorded final report. The selection rule is fixed before judging. An earlier, better answer cannot replace the final report.
- **Inputs:** the selected final, supporting investigation records and historical incident facts. The native judgments are retained, and all 42 Claude investigations were scored under the same policy. No change-caused pilot scenarios are mixed into these 21-scenario runs.
- **Evidence coverage:** native Edge Delta tool captures contain omitted or shortened arguments and results. The Claude records include the available saved tool calls and raw results; references to missing persisted-output files cannot reconstruct their contents. Scores therefore describe the available evidence, not identical capture completeness.
- **Attribution:** an investigator’s own PR can support a proposal it explicitly adopts. Another investigator’s work does not establish independent discovery, authorship or execution. Later PR snapshots cannot establish what was known earlier.
- **Validation:** all 72 judgments passed input-identity, score-format and exact-quotation checks. One Claude response needed a whitespace-only citation correction to match its source; the original response was retained, and no verdict or rationale was changed. No valid score was rerolled or manually overridden.

