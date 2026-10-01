"""Run the 21-scenario suite against an explicitly selected Kubernetes context.

Deploy the shop app and dependencies, apply fault manifests, and check cluster signals
for the expected failure. Reset retires only the injected resources and their persistent fault effects,
then verifies the baseline without replacing healthy services, data or credentials.
"""
import json
import secrets
import time
import datetime
import re
from .__main__ import command
from .app_manifests import OWNER, NAMESPACES, resources, meta


def kube(context, *args, stdin=None):
    if not context: raise ValueError("explicit Kubernetes context required")
    return command(["kubectl", "--context", context, *args], stdin, timeout=240)


def obj(context, kind, name, namespace=None):
    args = ["-n", namespace] if namespace else []
    raw = kube(context, *args, "get", kind, name, "--ignore-not-found", "-o", "json")
    return json.loads(raw) if raw.strip() else None


def owned(value):
    return value and value.get("metadata", {}).get("labels", {}).get("portable-benchmark") == "suite-v1"


def guard(context, require_deployed=True):
    for namespace in NAMESPACES:
        current = obj(context, "namespace", namespace)
        if current and not owned(current): raise ValueError("Refusing existing unowned namespace: " + namespace)
        if require_deployed and not current: raise ValueError("Deploy the full suite first: missing " + namespace)


def apply(context, manifest):
    return kube(context, "apply", "-f", "-", stdin=json.dumps(manifest))


def set_state(context, registry, tag, scenario="", retired_scenario="", reset_pending=False):
    return apply(context, {"apiVersion": "v1", "kind": "ConfigMap", "metadata": meta("suite-state", "benchmark-control"),
                           "data": {"registry": registry, "tag": tag, "scenario": scenario, "deployment_mode": "direct", "retired_scenario": retired_scenario, "reset_pending": str(reset_pending).lower(), "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")}})


def state(context):
    current = obj(context, "configmap", "suite-state", "benchmark-control")
    if not owned(current): raise ValueError("owned suite state missing")
    return current["data"]


def require_direct(context):
    current = obj(context, "configmap", "suite-state", "benchmark-control")
    if current and current.get("data", {}).get("deployment_mode") == "gitops":
        raise ValueError("This deployment is managed by Argo CD; use bench.gitops fault/reset and sync")


def deploy(context, registry, tag):
    require_direct(context)
    nodes = json.loads(kube(context, "get", "nodes", "-o", "json"))["items"]
    if not any(node.get("metadata", {}).get("labels", {}).get("kubernetes.io/arch") == "amd64" for node in nodes):
        raise ValueError("The original full-suite shop images require AMD64 workers; use an AMD64 cluster or the smoke suite on ARM64")
    guard(context, False)
    if obj(context, "namespace", "benchmark-control") and obj(context, "configmap", "suite-state", "benchmark-control"):
        raise ValueError("Suite already initialized; use reset to restore its disposable state")
    manifest = resources(secrets.token_urlsafe(32), secrets.token_urlsafe(32), registry, tag)
    # Record the deployment attempt before applying workloads, including partial failures.
    apply(context, {"apiVersion": "v1", "kind": "Namespace", "metadata": meta("benchmark-control")})
    set_state(context, registry, tag)
    # Do not print manifest/Secret bodies. Credentials travel only over kubectl stdin.
    apply(context, manifest)
    for item in manifest["items"]:
        if item["kind"] in ["Deployment", "StatefulSet"]:
            kube(context, "-n", item["metadata"]["namespace"], "rollout", "status",
                 item["kind"].lower() + "/" + item["metadata"]["name"], "--timeout=300s")
    result = verify(context, "healthy", 90)
    if not result["observed"]: raise ValueError("Pods rolled out but healthy end-to-end request is not established")
    return result


def json_stream(raw):
    decoder = json.JSONDecoder(); result = []
    while raw.strip():
        raw = raw.lstrip(); value, offset = decoder.raw_decode(raw); raw = raw[offset:]
        result.extend(value["items"] if value.get("kind") == "List" else [value])
    return result


def fault_objects(scenario, registry, tag):
    from .scenarios import render
    raw = command(["kubectl", "label", "--local", "-f", "-", "--overwrite", "portable-benchmark=suite-v1", "-o", "json"], render(scenario, registry, tag))
    return json_stream(raw)


def start(context, scenario):
    require_direct(context)
    guard(context)
    current = state(context)
    if current["scenario"] or current.get("reset_pending") == "true": raise ValueError("Complete retirement before starting another scenario")
    from .app_manifests import FLAG_FAULTS
    from . import retirement
    retirement.wait_baseline(context, timeout=0)
    if scenario in FLAG_FAULTS:
        objects = [retirement.flags(obj(context, "configmap", "flagd-config", "shop"), scenario)]
    else:
        objects = fault_objects(scenario, current["registry"], current["tag"])
    for value in objects:
        if not value["metadata"].get("namespace"):
            existing = obj(context, value["kind"], value["metadata"]["name"])
            if existing and not owned(existing): raise ValueError("Unowned cluster resource conflicts with scenario")
    # Record before mutation so a partially applied injection is still resettable.
    set_state(context, current["registry"], current["tag"], scenario)
    apply(context, {"apiVersion": "v1", "kind": "List", "items": objects})
    if scenario in ["quota-trap", "admission-webhook-outage"]:
        kube(context, "-n", "shop", "delete", "pod", "-l", "app.kubernetes.io/name=recommendation", "--wait=false")
    return {"scenario": scenario, "applied": True, "observed": False, "next": "run verify; successful apply is not fault confirmation"}


def reset(context, confirmed=False):
    if not confirmed: raise ValueError("reset requires --confirm-disposable; it retires the injected fault and its disposable fault data")
    require_direct(context)
    guard(context)
    current = state(context)
    scenario = current.get("scenario") or current.get("retired_scenario", "")
    from .app_manifests import FLAG_FAULTS
    from . import retirement
    # Record an incomplete retirement so a failed cleanup can be retried and a
    # new injection cannot silently start on top of residual fault state.
    set_state(context, current["registry"], current["tag"], retired_scenario=scenario, reset_pending=True)
    if scenario and scenario not in FLAG_FAULTS:
        objects = fault_objects(scenario, current["registry"], current["tag"])
        # A retained PV is removed after its claim, matching the parent helper.
        deleting = []
        for value in objects:
            if value["kind"] == "PersistentVolume": continue
            metadata = value["metadata"]
            existing = obj(context, value["kind"], metadata["name"], metadata.get("namespace"))
            if existing and not owned(existing): raise ValueError("refusing to retire unowned " + value["kind"] + "/" + metadata["name"])
            deleting.append(value)
        if deleting:
            kube(context, "delete", "-f", "-", "--ignore-not-found", "--wait=false", stdin=json.dumps({"apiVersion": "v1", "kind": "List", "items": deleting}))
    flags = obj(context, "configmap", "flagd-config", "shop")
    baseline = retirement.flags(flags)
    if baseline["data"] != flags["data"]: apply(context, baseline)
    retirement.wait_pruned(context)
    actions = retirement.restore(context, scenario)
    checks = retirement.wait_baseline(context)
    result = verify(context, "healthy", 180)
    if not result["observed"]: raise ValueError("fault retired, but the healthy application path has not recovered")
    set_state(context, current["registry"], current["tag"])
    result.update(retirement=checks, cleanup_actions=actions)
    return result


def http(context, service="frontend", path="/"):
    if service != "frontend" or path not in ["/", "/api/products"]:
        raise ValueError("unsupported frontend probe target")
    # The original frontend contains Node, not the Python runtime used by the old fixture.
    script = "fetch(" + json.dumps("http://frontend.shop.svc.cluster.local:8080" + path) + ", {signal: AbortSignal.timeout(10000)}).then(async r => console.log(JSON.stringify({status:r.status,body:(await r.text()).slice(0,65536)}))).catch(() => console.log(JSON.stringify({status:0,body:'connection failed'})))"
    return json.loads(kube(context, "-n", "shop", "exec", "deployment/frontend", "--", "/nodejs/bin/node", "-e", script))


def collect(context):
    result = {}
    for namespace in ["batch", "shop"]:
        result[namespace] = json.loads(kube(context, "-n", namespace, "get", "pods,events,pvc", "-o", "json"))["items"]
    return result


def check(scenario, evidence):
    """Pure outcome predicates; tests feed observed Kubernetes/API records."""
    if scenario == "healthy": return evidence.get("http", {}).get("status") == 200 and evidence.get("catalog", {}).get("status") == 200
    http_result = evidence.get("http", {})
    http_body = http_result.get("body", "")
    app_logs = evidence.get("application_logs", {})
    if scenario == "payment-failure":
        return "card token rejected by processor" in app_logs.get("payment", "")
    if scenario == "cart-failure":
        return "cart-store-secondary" in app_logs.get("cart", "") and bool(re.search(r"error|timeout|deadline|exception", app_logs.get("cart", ""), re.I))
    if scenario == "stale-db-credentials":
        return "password authentication failed" in app_logs.get("postgres", "") and "shop_user" in app_logs.get("postgres", "")
    if scenario == "pg-lock-hold":
        return evidence.get("exclusive_locks", 0) > 0 and evidence.get("lock_waiters", 0) > 0
    if scenario == "netpol-isolation":
        return evidence.get("cart_policy_present", False) and bool(re.search(r"deadline|unavailable", app_logs.get("frontend", "") + app_logs.get("checkout", ""), re.I))
    if scenario == "traffic-flood":
        return bool(re.search(r"(?:concurrency flag changed|vus)[^\n]*\b50\b", app_logs.get("load-generator", ""), re.I))
    items = evidence.get("batch", []) + evidence.get("shop", [])
    pods = [item for item in items if item.get("kind") == "Pod"]
    statuses = [status for pod in pods for status in pod.get("status", {}).get("containerStatuses", [])]
    reasons = [status.get("state", {}).get("waiting", {}).get("reason", "") for status in statuses]
    terminated = [status.get("lastState", {}).get("terminated", {}).get("reason", "") for status in statuses]
    messages = "\n".join(item.get("message", "") for item in items if item.get("kind") == "Event")
    logs = evidence.get("logs", "")
    if scenario == "quota-trap": return "requests.cpu" in messages and ("must specify" in messages or "quota" in messages)
    if scenario == "admission-webhook-outage": return "pod-policy" in messages and "webhook" in messages
    if scenario == "crashloop":
        for pod in pods:
            metadata = pod.get("metadata", {})
            if not (metadata.get("name", "").startswith("report-generator-") or metadata.get("labels", {}).get("app") == "report-generator"):
                continue
            backoff = any(item.get("kind") == "Event" and item.get("reason") == "BackOff" and item.get("involvedObject", {}).get("name") == metadata.get("name") for item in items)
            for status in pod.get("status", {}).get("containerStatuses", []):
                if status.get("state", {}).get("waiting", {}).get("reason") == "CrashLoopBackOff": return True
                if status.get("restartCount", 0) >= 2 and status.get("lastState", {}).get("terminated", {}).get("exitCode") == 1 and backoff:
                    return True
        return False
    if scenario == "oom": return "OOMKilled" in terminated
    if scenario == "image-pull": return any(r in reasons for r in ["ImagePullBackOff", "ErrImagePull"])
    if scenario == "missing-config-key": return "CreateContainerConfigError" in reasons
    if scenario == "probe-fail": return any(p.get("status", {}).get("phase") == "Running" and any(not c.get("ready") for c in p.get("status", {}).get("containerStatuses", [])) for p in pods) and "Readiness probe failed" in messages
    if scenario in ["pending-volume-claim", "volume-affinity-conflict"]:
        marker = "storageclass" if scenario == "pending-volume-claim" else "affinity"
        return any(p.get("status", {}).get("phase") == "Pending" for p in pods) and marker in messages.lower()
    if scenario == "log-error-burst": return logs.count("ERROR upstream gateway timeout") >= 3
    if scenario == "slow-leak":
        return len(set(re.findall(r"cache grew to (\d+)MiB", logs))) >= 2
    if scenario == "shm-exhaustion": return "scratch write failed" in logs
    if scenario == "redis-pressure": return "write rejected (OOM)" in logs
    if scenario == "multi-fault": return check("crashloop", evidence) and check("redis-pressure", evidence)
    if scenario == "composite-noise-fault": return check("image-pull", evidence) and check("log-error-burst", evidence)
    return False


def observe(context, scenario):
    evidence = collect(context)
    evidence["http"] = http(context)
    if scenario == "healthy": evidence["catalog"] = http(context, path="/api/products")
    if scenario == "netpol-isolation":
        evidence["cart_policy_present"] = bool(obj(context, "networkpolicy", "restrict-cart-ingress", "shop"))
    if scenario == "pg-lock-hold":
        queries = {"exclusive_locks": "SELECT count(*) FROM pg_locks WHERE relation='catalog.products'::regclass AND mode='AccessExclusiveLock' AND granted",
                   "lock_waiters": "SELECT count(*) FROM pg_stat_activity WHERE wait_event_type='Lock' AND datname='shop_db'"}
        for key, query in queries.items():
            evidence[key] = int(kube(context, "-n", "datastore", "exec", "statefulset/postgres", "--", "psql", "-U", "shop", "-d", "shop_db", "-tAc", query).strip())
    since = state(context).get("started_at")
    log_window = ["--since-time=" + since] if since else ["--since=5m"]
    evidence["application_logs"] = {}
    for service in ["frontend", "checkout", "cart", "payment", "load-generator", "product-catalog", "postgres"]:
        namespace, target = ("datastore", "statefulset/postgres") if service == "postgres" else ("shop", "deployment/" + service)
        try: evidence["application_logs"][service] = kube(context, "-n", namespace, "logs", target, *log_window, "--tail=200")
        except RuntimeError: evidence["application_logs"][service] = ""
    logs = []
    for pod in evidence["batch"]:
        if pod.get("kind") != "Pod": continue
        for previous in [False, True]:
            try: logs.append(kube(context, "-n", "batch", "logs", pod["metadata"]["name"], "--tail=100", *(["--previous"] if previous else [])))
            except RuntimeError: pass
    evidence["logs"] = "\n".join(logs)
    return evidence


def verify(context, scenario, timeout=120):
    if not 0 <= timeout <= 3600: raise ValueError("timeout must be between 0 and 3600 seconds")
    guard(context)
    current = state(context)
    if scenario == "healthy" and current["scenario"]: raise ValueError("Reset the active injection before verifying the healthy baseline")
    if scenario != "healthy" and current["scenario"] != scenario: raise ValueError("Scenario is not the recorded active injection")
    deadline = time.monotonic() + timeout; last = {}
    while True:
        try:
            last = observe(context, scenario)
            observed = check(scenario, last)
        except (RuntimeError, ValueError) as error:
            last = {"observation_error": str(error)}
            observed = False
        if observed or time.monotonic() >= deadline: break
        time.sleep(3)
    return {"scenario": scenario, "observed": observed, "observation": last, "meaning": "fault/healthy fixture evidence only; not product detection or remediation success"}
