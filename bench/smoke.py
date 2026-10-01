"""Define the six smoke scenarios and their cause, impact, and mitigation.

Generate Kubernetes manifests for the healthy HTTP app or a selected fault,
embedding fixture.py in a ConfigMap mounted by the app container.
"""
from pathlib import Path

NAMESPACE = "incident-bench"
IMAGE = "python:3.12.10-alpine3.21@sha256:9c51ecce261773a684c8345b2d4673700055c513b4d54bc0719337d3e4ee552e"
SCENARIOS = {
    "multi-fault": {
        "cause": "Two faults coexist: FAULT_MODE=crash aborts startup and the readiness probe targets 9090 instead of 8080.",
        "impact": "The API remains unavailable after correcting either fault alone.",
        "mitigation": "Restore healthy mode AND the readiness probe port to 8080; verify rollout and ready endpoints.",
    },
    "crashloop": {
        "cause": "The API container's FAULT_MODE=crash causes startup to raise an exception.",
        "impact": "The API deployment cannot serve requests.",
        "mitigation": "Restore FAULT_MODE=healthy on the API deployment; verify readiness.",
    },
    "probe-mismatch": {
        "cause": "The readiness probe targets port 9090 while the HTTP server listens on 8080.",
        "impact": "The API is removed from ready Service endpoints although the process runs.",
        "mitigation": "Restore the API readiness probe port to 8080; verify ready endpoints.",
    },
    "image-pull": {
        "cause": "The API image tag is deliberately nonexistent.",
        "impact": "Replacement API pods cannot start.",
        "mitigation": "Restore the recorded baseline image reference; verify its availability and rollout.",
    },
    "unbounded-memory": {
        "cause": "FAULT_MODE=allocate repeatedly retains allocations without a bound.",
        "impact": "The API container reaches its memory limit and is killed repeatedly.",
        "mitigation": "Restore healthy mode or remove/bound retained allocation; raising the limit alone is not a fix.",
    },
    "missing-storage-class": {
        "cause": "The API mounts a new PVC requesting the nonexistent incident-bench-missing StorageClass.",
        "impact": "The API pod remains Pending; the Service cannot serve requests.",
        "mitigation": "Remove the newly introduced disposable volume dependency or provide a valid class; never delete an unknown bound volume.",
    },
}


def resources(scenario=None, image=IMAGE):
    if scenario is not None and scenario not in SCENARIOS:
        raise ValueError("unknown scenario")
    labels = {"app": "incident-bench-api", "benchmark.fixture": "portable-v1"}
    container = {
        "name": "api", "image": image, "imagePullPolicy": "IfNotPresent",
        "command": ["python", "-u", "/fixture/fixture.py"],
        "env": [{"name": "FAULT_MODE", "value": "healthy"}],
        "ports": [{"containerPort": 8080}],
        "readinessProbe": {"httpGet": {"path": "/health", "port": 8080}, "periodSeconds": 3},
        "resources": {"requests": {"cpu": "50m", "memory": "32Mi"}, "limits": {"cpu": "250m", "memory": "96Mi"}},
        "securityContext": {"allowPrivilegeEscalation": False, "runAsNonRoot": True, "runAsUser": 10001, "capabilities": {"drop": ["ALL"]}, "seccompProfile": {"type": "RuntimeDefault"}},
        "volumeMounts": [{"name": "fixture", "mountPath": "/fixture", "readOnly": True}],
    }
    pod = {"automountServiceAccountToken": False, "containers": [container], "volumes": [{"name": "fixture", "configMap": {"name": "fixture"}}]}
    if scenario in ["crashloop", "multi-fault"]: container["env"][0]["value"] = "crash"
    if scenario == "unbounded-memory": container["env"][0]["value"] = "allocate"
    if scenario in ["probe-mismatch", "multi-fault"]: container["readinessProbe"]["httpGet"]["port"] = 9090
    if scenario == "image-pull": container["image"] = "python:incident-bench-nonexistent-00000000"
    objects = [
        {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": NAMESPACE, "labels": {"benchmark.fixture": "portable-v1"}}},
        {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "fixture", "namespace": NAMESPACE}, "data": {"fixture.py": Path(__file__).with_name("fixture.py").read_text()}},
        {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": "api", "namespace": NAMESPACE}, "spec": {"replicas": 1, "strategy": {"type": "Recreate"}, "selector": {"matchLabels": labels}, "template": {"metadata": {"labels": labels}, "spec": pod}}},
        {"apiVersion": "v1", "kind": "Service", "metadata": {"name": "api", "namespace": NAMESPACE}, "spec": {"selector": labels, "ports": [{"port": 8080, "targetPort": 8080}]}},
    ]
    if scenario == "missing-storage-class":
        container["volumeMounts"].append({"name": "data", "mountPath": "/data"})
        pod["volumes"].append({"name": "data", "persistentVolumeClaim": {"claimName": "fixture-data"}})
        objects.insert(2, {"apiVersion": "v1", "kind": "PersistentVolumeClaim", "metadata": {"name": "fixture-data", "namespace": NAMESPACE}, "spec": {"accessModes": ["ReadWriteOnce"], "storageClassName": "incident-bench-missing", "resources": {"requests": {"storage": "16Mi"}}}})
    return {"apiVersion": "v1", "kind": "List", "items": objects}
