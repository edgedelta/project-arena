# Per-scenario results

Results for all 21 incident scenarios. Each verdict uses the same scoring rubric across the four configurations. See [metric definitions](../README.md#what-the-metrics-mean) and [aggregate results](benchmark-results.md).

Native products initiated investigations through their detection stacks. Claude was launched through an alert or customer report; its detection performance was not independently measured. **Not investigated** means no native investigation was available for scoring, rather than an incorrect answer.

[Download the displayed results as CSV](scenario-results.csv).

## Detection

A dash means detection was not independently measured for Claude.

| Scenario | Edge Delta native | Grafana native | Claude + edx | Claude + gcx |
|:---|:---:|:---:|:---:|:---:|
| `admission-webhook-outage` | Detected | Detected | — | — |
| `cart-failure` | Detected | Not detected | — | — |
| `composite-noise-fault` | Detected | Detected | — | — |
| `crashloop` | Detected | Detected | — | — |
| `image-pull` | Detected | Detected | — | — |
| `log-error-burst` | Detected | Not detected | — | — |
| `missing-config-key` | Detected | Detected | — | — |
| `multi-fault` | Detected | Detected | — | — |
| `netpol-isolation` | Not detected | Not detected | — | — |
| `oom` | Detected | Detected | — | — |
| `payment-failure` | Detected | Not detected | — | — |
| `pending-volume-claim` | Detected | Detected | — | — |
| `pg-lock-hold` | Detected | Not detected | — | — |
| `probe-fail` | Detected | Detected | — | — |
| `quota-trap` | Detected | Detected | — | — |
| `redis-pressure` | Not detected | Not detected | — | — |
| `shm-exhaustion` | Detected | Detected | — | — |
| `slow-leak` | Not detected | Not detected | — | — |
| `stale-db-credentials` | Detected | Not detected | — | — |
| `traffic-flood` | Detected | Not detected | — | — |
| `volume-affinity-conflict` | Detected | Detected | — | — |

## Root cause analysis

| Scenario | Edge Delta native | Grafana native | Claude + edx | Claude + gcx |
|:---|:---:|:---:|:---:|:---:|
| `admission-webhook-outage` | Correct | Correct | Correct | Correct |
| `cart-failure` | Correct | Not investigated | Correct | Correct |
| `composite-noise-fault` | Partial | Partial | Partial | Partial |
| `crashloop` | Correct | Incorrect | Correct | Correct |
| `image-pull` | Correct | Correct | Correct | Correct |
| `log-error-burst` | Incorrect | Not investigated | Incorrect | Correct |
| `missing-config-key` | Correct | Correct | Correct | Correct |
| `multi-fault` | Correct | Incorrect | Partial | Partial |
| `netpol-isolation` | Not investigated | Not investigated | Correct | Correct |
| `oom` | Correct | Correct | Correct | Correct |
| `payment-failure` | Correct | Not investigated | Correct | Correct |
| `pending-volume-claim` | Correct | Correct | Correct | Correct |
| `pg-lock-hold` | Correct | Not investigated | Correct | Correct |
| `probe-fail` | Correct | Correct | Correct | Correct |
| `quota-trap` | Correct | Correct | Correct | Correct |
| `redis-pressure` | Not investigated | Not investigated | Correct | Correct |
| `shm-exhaustion` | Correct | Correct | Correct | Correct |
| `slow-leak` | Not investigated | Not investigated | Correct | Correct |
| `stale-db-credentials` | Correct | Not investigated | Correct | Correct |
| `traffic-flood` | Incorrect | Not investigated | Correct | Correct |
| `volume-affinity-conflict` | Correct | Correct | Correct | Correct |

## Blast radius

| Scenario | Edge Delta native | Grafana native | Claude + edx | Claude + gcx |
|:---|:---:|:---:|:---:|:---:|
| `admission-webhook-outage` | Partial | Partial | Incorrect | Incorrect |
| `cart-failure` | Partial | Not investigated | Correct | Correct |
| `composite-noise-fault` | Partial | Partial | Correct | Partial |
| `crashloop` | Correct | Correct | Correct | Correct |
| `image-pull` | Correct | Correct | Correct | Correct |
| `log-error-burst` | Incorrect | Not investigated | Incorrect | Correct |
| `missing-config-key` | Correct | Correct | Correct | Correct |
| `multi-fault` | Correct | Partial | Incorrect | Correct |
| `netpol-isolation` | Not investigated | Not investigated | Correct | Correct |
| `oom` | Correct | Correct | Correct | Correct |
| `payment-failure` | Correct | Not investigated | Correct | Correct |
| `pending-volume-claim` | Correct | Correct | Correct | Correct |
| `pg-lock-hold` | Correct | Not investigated | Correct | Correct |
| `probe-fail` | Correct | Correct | Correct | Correct |
| `quota-trap` | Partial | Partial | Correct | Correct |
| `redis-pressure` | Not investigated | Not investigated | Correct | Correct |
| `shm-exhaustion` | Correct | Correct | Correct | Correct |
| `slow-leak` | Not investigated | Not investigated | Correct | Correct |
| `stale-db-credentials` | Correct | Not investigated | Correct | Incorrect |
| `traffic-flood` | Partial | Not investigated | Correct | Correct |
| `volume-affinity-conflict` | Correct | Correct | Correct | Correct |

## Supported final mitigation

**Supported:** a supported fix or containment. **Partial:** covers some causal faults. **Candidate:** essential causal, target, or safety decisions remain. **Incorrect / unsafe:** the final retains incorrect or unsafe advice. **No proposal:** no final remedy. These verdicts evaluate proposals, not executed repairs.

| Scenario | Edge Delta native | Grafana native | Claude + edx | Claude + gcx |
|:---|:---:|:---:|:---:|:---:|
| `admission-webhook-outage` | Supported | Supported | Supported | Supported |
| `cart-failure` | Candidate | Not investigated | Supported | Supported |
| `composite-noise-fault` | Supported | Candidate | Supported | Supported |
| `crashloop` | Supported | Candidate | Supported | Supported |
| `image-pull` | Supported | Supported | Supported | Supported |
| `log-error-burst` | No proposal | Not investigated | Incorrect / unsafe | Supported |
| `missing-config-key` | Candidate | Candidate | Incorrect / unsafe | Incorrect / unsafe |
| `multi-fault` | Supported | Incorrect / unsafe | Incorrect / unsafe | Incorrect / unsafe |
| `netpol-isolation` | Not investigated | Not investigated | Supported | Supported |
| `oom` | Candidate | Incorrect / unsafe | Incorrect / unsafe | Supported |
| `payment-failure` | Candidate | Not investigated | Supported | Incorrect / unsafe |
| `pending-volume-claim` | Candidate | Supported | Supported | Supported |
| `pg-lock-hold` | Candidate | Not investigated | Supported | Incorrect / unsafe |
| `probe-fail` | Supported | Candidate | Supported | Incorrect / unsafe |
| `quota-trap` | Partial | Supported | Supported | Supported |
| `redis-pressure` | Not investigated | Not investigated | Supported | Supported |
| `shm-exhaustion` | Supported | Supported | Supported | Supported |
| `slow-leak` | Not investigated | Not investigated | Supported | Supported |
| `stale-db-credentials` | Supported | Not investigated | Supported | Supported |
| `traffic-flood` | No proposal | Not investigated | Supported | Supported |
| `volume-affinity-conflict` | Candidate | Candidate | Incorrect / unsafe | Incorrect / unsafe |

## Implementation readiness

**Reviewable:** the correction and essential details are specified; normal implementation and rollout checks may remain. **Details missing:** essential details remain unresolved. **Not applicable:** no remedy was proposed.

| Scenario | Edge Delta native | Grafana native | Claude + edx | Claude + gcx |
|:---|:---:|:---:|:---:|:---:|
| `admission-webhook-outage` | Reviewable | Reviewable | Reviewable | Reviewable |
| `cart-failure` | Details missing | Not investigated | Reviewable | Reviewable |
| `composite-noise-fault` | Reviewable | Details missing | Reviewable | Reviewable |
| `crashloop` | Reviewable | Details missing | Reviewable | Reviewable |
| `image-pull` | Reviewable | Reviewable | Reviewable | Reviewable |
| `log-error-burst` | Not applicable | Not investigated | Details missing | Reviewable |
| `missing-config-key` | Details missing | Details missing | Details missing | Details missing |
| `multi-fault` | Reviewable | Details missing | Details missing | Details missing |
| `netpol-isolation` | Not investigated | Not investigated | Reviewable | Reviewable |
| `oom` | Details missing | Details missing | Details missing | Reviewable |
| `payment-failure` | Details missing | Not investigated | Reviewable | Details missing |
| `pending-volume-claim` | Details missing | Reviewable | Reviewable | Reviewable |
| `pg-lock-hold` | Details missing | Not investigated | Reviewable | Details missing |
| `probe-fail` | Reviewable | Details missing | Reviewable | Details missing |
| `quota-trap` | Reviewable | Reviewable | Reviewable | Reviewable |
| `redis-pressure` | Not investigated | Not investigated | Reviewable | Reviewable |
| `shm-exhaustion` | Reviewable | Reviewable | Reviewable | Reviewable |
| `slow-leak` | Not investigated | Not investigated | Reviewable | Reviewable |
| `stale-db-credentials` | Reviewable | Not investigated | Reviewable | Reviewable |
| `traffic-flood` | Not applicable | Not investigated | Reviewable | Reviewable |
| `volume-affinity-conflict` | Details missing | Details missing | Details missing | Details missing |
