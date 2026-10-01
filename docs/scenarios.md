# Scenario support

The full suite includes implementations for all 21 scenarios below. **Live validation is pending for every scenario.** Included manifests and passing offline tests do not establish that a fault has been reproduced successfully on a cluster.

All scenarios require the full-suite application and locally built or registry-hosted fault images. See the [build and deployment instructions](../scenarios/README.md). Select `full` in your run configuration, then use `python3 -m bench catalog` to list scenarios and `python3 -m bench verify --context YOUR_CONTEXT` to check the configured fault after injection.

| Scenario | Implementation | Live validation | Additional requirements or behavior |
|---|---|---|---|
| `crashloop` | Included | Pending | — |
| `payment-failure` | Included | Pending | — |
| `image-pull` | Included | Pending | The `missing-hotfix` image tag must not exist. |
| `cart-failure` | Included | Pending | — |
| `probe-fail` | Included | Pending | — |
| `missing-config-key` | Included | Pending | — |
| `log-error-burst` | Included | Pending | — |
| `oom` | Included | Pending | — |
| `redis-pressure` | Included | Pending | — |
| `quota-trap` | Included | Pending | Injection recreates the recommendation pod to trigger quota admission. |
| `slow-leak` | Included | Pending | Allow more than one minute for multiple memory-growth observations. |
| `shm-exhaustion` | Included | Pending | — |
| `netpol-isolation` | Included | Pending | Requires a NetworkPolicy-enforcing CNI; default kind networking does not enforce policies. |
| `pending-volume-claim` | Included | Pending | The StorageClass requested by the fault must be absent. |
| `stale-db-credentials` | Included | Pending | — |
| `volume-affinity-conflict` | Included | Pending | No node may have `storage-tier=nvme-archive`; creates a disposable cluster-scoped PV. |
| `pg-lock-hold` | Included | Pending | — |
| `multi-fault` | Included | Pending | Verification requires both the crashloop and Redis write-rejection signals. |
| `admission-webhook-outage` | Included | Pending | Injection recreates the recommendation pod to trigger the unavailable webhook. |
| `composite-noise-fault` | Included | Pending | — |
| `traffic-flood` | Included | Pending | Changes original k6 browse concurrency from 5 to 50 sessions; achieved throughput depends on request latency. |

## Smoke fixture

The separate `smoke` suite includes six smaller scenarios: `crashloop`, `probe-mismatch`, `image-pull`, `unbounded-memory`, `missing-storage-class`, and `multi-fault`. These also require live validation. See the [smoke quick start](../README.md#how-to-run-scenarios).

The suites use different applications. In particular, full-suite `multi-fault` combines a crashloop with Redis pressure; smoke `multi-fault` combines a startup failure with an incorrect readiness-probe port. Results from the two suites should not be combined as equivalent cases.

## Scenario scoring

Full-suite scoring automatically loads each scenario’s bundled `answer-key.json`, containing cause, impact, and mitigation. For a customized application, provide an updated key through `packet --truth` or the run configuration. See [product and judge integration](../README.md#how-to-connect-your-product).
