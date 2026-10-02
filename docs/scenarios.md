# Scenario support

The full suite includes the 21 scenarios below. The table lists prerequisites and behavior to account for when running each fault.

All scenarios require the full-suite application and locally built or registry-hosted fault images. See the [build and deployment instructions](../scenarios/README.md). Select `full` in your run configuration, then use `python3 -m bench catalog` to list scenarios and `python3 -m bench verify --context YOUR_CONTEXT` to check the configured fault after injection.

| Scenario | Additional requirements or behavior |
|---|---|
| `crashloop` | — |
| `payment-failure` | — |
| `image-pull` | The `missing-hotfix` image tag must not exist. |
| `cart-failure` | — |
| `probe-fail` | — |
| `missing-config-key` | — |
| `log-error-burst` | — |
| `oom` | — |
| `redis-pressure` | — |
| `quota-trap` | Injection recreates the recommendation pod to trigger quota admission. |
| `slow-leak` | Allow more than one minute for multiple memory-growth observations. |
| `shm-exhaustion` | — |
| `netpol-isolation` | Requires a NetworkPolicy-enforcing CNI; default kind networking does not enforce policies. |
| `pending-volume-claim` | The StorageClass requested by the fault must be absent. |
| `stale-db-credentials` | — |
| `volume-affinity-conflict` | No node may have `storage-tier=nvme-archive`; creates a disposable cluster-scoped PV. |
| `pg-lock-hold` | — |
| `multi-fault` | Verification requires both the crashloop and Redis write-rejection signals. |
| `admission-webhook-outage` | Injection recreates the recommendation pod to trigger the unavailable webhook. |
| `composite-noise-fault` | — |
| `traffic-flood` | Changes original k6 browse concurrency from 5 to 50 sessions; achieved throughput depends on request latency. |

## Smoke fixture

The separate `smoke` suite includes six smaller scenarios: `crashloop`, `probe-mismatch`, `image-pull`, `unbounded-memory`, `missing-storage-class`, and `multi-fault`. See the [smoke quick start](../README.md#how-to-run-scenarios).

The suites use different applications. In particular, full-suite `multi-fault` combines a crashloop with Redis pressure; smoke `multi-fault` combines a startup failure with an incorrect readiness-probe port. Results from the two suites should not be combined as equivalent cases.

## Scenario scoring

Full-suite scoring automatically loads each scenario’s bundled `answer-key.json`, containing cause, impact, and mitigation. For a customized application, provide an updated key through `packet --truth` or the run configuration. See [product and judge integration](../README.md#how-to-connect-your-product).
