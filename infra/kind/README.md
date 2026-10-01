# Local kind cluster with NetworkPolicy

This setup uses Cilium so the `netpol-isolation` scenario can enforce its policy. Run from the project root with Docker, kind, kubectl and Helm installed. Create a new cluster; do not install a second CNI over kind's default networking.

The full suite requires AMD64 workers because its prebuilt application images are AMD64-only. On Apple Silicon, use native kind for the smoke suite or use AMD64 remote workers for the full suite. The commands below are for an AMD64 full-suite cluster.

```sh
kind create cluster --name incident-bench --config infra/kind/cluster.yaml
helm upgrade --install cilium cilium \
  --repo https://helm.cilium.io --version 1.20.2 \
  --kube-context kind-incident-bench --namespace kube-system \
  --set ipam.mode=kubernetes --set operator.replicas=1 \
  --wait --timeout 5m
kubectl --context kind-incident-bench wait --for=condition=Ready nodes --all --timeout=180s
python3 -m bench.scenarios build-images --kind-name incident-bench
```

The configuration keeps kube-proxy and disables kind's default CNI. These settings follow the [Cilium kind installation guide](https://docs.cilium.io/en/stable/installation/kind/). Use current Docker Desktop on macOS; Linux hosts need the kernel features required by Cilium. Select image architecture to match the kind nodes as described in the [root guide](../../README.md#local-kind).

After deploying the application, verify a healthy business response before injecting `netpol-isolation`. `bench verify` then checks that cart becomes unreachable and frontend reports the downstream failure; after reset, verify the healthy request path again. A running CNI alone does not demonstrate that the policy scenario worked.

Delete the cluster with `python3 -m bench cluster delete --confirm-delete`.
