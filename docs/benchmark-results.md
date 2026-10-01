# Benchmark results

We compared Edge Delta’s native AI investigations with Grafana’s native AI investigations across 21 Kubernetes incident scenarios per product. The tables evaluate detection and the quality of 30 completed investigations using the [scoring rubric](scoring-rubric-v1.0.0.md).

This page presents detection, diagnosis, and final recommendation results. Action-safety and intermediate-advice scores are not displayed here; the scorer still evaluates them separately.

## All investigated scenarios

| Metric | Edge Delta native | Grafana native |
| --- | ---: | ---: |
| Detection | 18/21 (85.7%) | 12/21 (57.1%) |
| Root cause analysis | 15/18 (83.3%) | 9/12 (75.0%) |
| Blast radius | 12/18 (66.7%) | 8/12 (66.7%) |
| Causal change identification | — | — |
| Final mitigation | 8/18 (44.4%) | 5/12 (41.7%) |
| Implementation readiness | 9/16 (56.2%) | 5/12 (41.7%) |

Detection uses all 21 scenarios per product, including scenarios without a detected investigation during their observation window. The remaining metrics use the 18 Edge Delta and 12 Grafana investigations, excluding not-applicable values. Implementation readiness excludes two Edge Delta investigations with no mitigation proposal, hence its denominator of 16. These cohorts contain different scenarios; compare the matched subset below as well.

Causal change identification is **not applicable to all 30 investigations**: these full runs did not establish the controlled, accessible introducing changes required by that dimension. The dash means zero eligible cases, not a score of zero. Missing evidence is distinct from not applicable.

## Scenarios investigated by both products

These 12 scenarios have an investigation from each product. The comparison controls for which scenarios were investigated; it excludes the additional scenarios detected only by Edge Delta. Detection is 100% here by construction and is not a replacement for the 21-scenario detection result.

| Metric | Edge Delta native | Grafana native |
| --- | ---: | ---: |
| Detection | 12/12 (100.0%) | 12/12 (100.0%) |
| Root cause analysis | 11/12 (91.7%) | 9/12 (75.0%) |
| Blast radius | 9/12 (75.0%) | 8/12 (66.7%) |
| Causal change identification | — | — |
| Final mitigation | 7/12 (58.3%) | 5/12 (41.7%) |
| Implementation readiness | 8/12 (66.7%) | 5/12 (41.7%) |

Each product was tested in a separate run. The shared-scenario table compares the same incident types, not simultaneous investigations.

## Final mitigation breakdown

| Verdict | Edge Delta native | Grafana native |
| --- | --- | --- |
| supported | 8/18 (44.4%) | 5/12 (41.7%) |
| partial | 1/18 (5.6%) | 0/12 (0.0%) |
| candidate | 7/18 (38.9%) | 5/12 (41.7%) |
| incorrect_or_unsafe | 0/18 (0.0%) | 2/12 (16.7%) |
| none | 2/18 (11.1%) | 0/12 (0.0%) |
| insufficient_final_evidence | 0/18 (0.0%) | 0/12 (0.0%) |

A supported proposal specifies a causal fix or bounded containment without active incorrect or unsafe final advice. A partial proposal covers only part of the incident. A candidate still needs an essential causal, target or safety decision. Implementation readiness is assessed separately: a causal correction can be supported while an essential implementation detail remains unresolved.

Only the selected final report earns final mitigation credit. An earlier mistake that was corrected or omitted is assessed under intermediate advice, not used to fail the final recommendation. Proposals, approvals and PRs do not establish that a repair ran or that service recovered.

## Method and evidence

- **Judge:** GPT-6-Astra through OpenRouter, with high reasoning and tools disabled. Both products used the same settings and rubric.
- **Inputs:** each investigation’s delivered final report and supporting records, compared with the scenario’s answer key. Earlier answers cannot replace the final report to earn a better score.
- **Detection:** determined from the recorded observation window, independently of the judge.
- **Validation:** all 30 judgments passed checks for matching inputs, valid scores, and exact supporting quotations. No scores were manually overridden.
- **Attribution:** a referenced PR supports only the proposal explicitly adopted in the investigation. Another investigator’s work does not establish independent discovery or a completed repair.
