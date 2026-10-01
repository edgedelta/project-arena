"""Render the original shop topology with disposable database credentials.

Bundled manifests preserve the services, selectors, resources, persistent stores,
and image digests used by the benchmark. Registry/tag arguments select fault images;
the application uses its separately pinned public images.
"""
import json
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1] / "scenarios" / "shop"
OWNER = {"portable-benchmark": "suite-v1"}
NAMESPACES = ["benchmark-control", "shop", "datastore", "batch", "platform-ops", "telemetry"]
FLAG_FAULTS = {"payment-failure": ("paymentStrictTokenCheck", "100%"),
               "cart-failure": ("cartSecondaryStoreShare", "100%"),
               "traffic-flood": ("browseJourneyConcurrency", "50")}


def meta(name, namespace=None, labels=None):
    out = {"name": name, "labels": dict(OWNER, **(labels or {}))}
    if namespace: out["namespace"] = namespace
    return out


def flag_config(scenario=None):
    values = json.loads((ROOT / "flags.json").read_text())
    if scenario in FLAG_FAULTS:
        key, variant = FLAG_FAULTS[scenario]
        values["flags"][key]["defaultVariant"] = variant
    return {"apiVersion": "v1", "kind": "ConfigMap", "metadata": meta("flagd-config", "shop"),
            "data": {"flags.json": json.dumps(values, indent=2)}}


def secret(name, namespace, data):
    return {"apiVersion": "v1", "kind": "Secret", "metadata": meta(name, namespace), "type": "Opaque", "stringData": data}


def resources(admin_password, app_password, registry="fixture.local", tag="v1"):
    objects = [{"apiVersion": "v1", "kind": "Namespace", "metadata": meta(ns)} for ns in NAMESPACES]
    objects += collector_resources()
    objects += [flag_config(), secret("postgres", "datastore", {"POSTGRES_PASSWORD": admin_password}),
                secret("db-maintenance", "batch", {"PGUSER": "shop", "PGPASSWORD": admin_password})]
    for obj in json.loads((ROOT / "manifests.json").read_text())["items"]:
        obj["metadata"].setdefault("labels", {}).update(OWNER)
        if obj["kind"] == "ConfigMap" and obj["metadata"]["name"] == "postgres-init":
            # SQL literal escaping is separate from URI quoting below.
            obj["data"]["init.sql"] = obj["data"]["init.sql"].replace("'shop_password'", "'" + app_password.replace("'", "''") + "'")
        template = obj.get("spec", {}).get("template")
        if template:
            template["metadata"].setdefault("labels", {}).update(OWNER)
            # Original public shop images were built for AMD64; avoid random scheduling
            # onto ARM nodes in mixed-architecture clusters.
            if any("public.ecr.aws/v4z2v9g0/webshop/" in c["image"] for c in template["spec"].get("containers", [])):
                template["spec"].setdefault("nodeSelector", {})["kubernetes.io/arch"] = "amd64"
            for container in template["spec"].get("containers", []):
                for env in container.get("env", []):
                    if env["name"] == "DB_CONNECTION_STRING":
                        env["value"] = "postgres://shop_user:" + quote(app_password, safe="") + "@postgres.datastore.svc.cluster.local:5432/shop_db?sslmode=disable"
        objects.append(obj)
    return {"apiVersion": "v1", "kind": "List", "items": objects}


def collector_resources():
    labels = {"app.kubernetes.io/name": "otel-collector"}
    container = {"name": "collector", "image": "otel/opentelemetry-collector-contrib:0.139.0@sha256:faf125d656fa47cea568b2f3b4494efd2525083bc75c1e96038bc23f05cd68fd",
                 "args": ["--config=/etc/otel/collector.yaml"],
                 "ports": [{"containerPort": 4317}, {"containerPort": 4318}],
                 "resources": {"requests": {"cpu": "100m", "memory": "128Mi"}, "limits": {"memory": "512Mi"}},
                 "volumeMounts": [{"name": "config", "mountPath": "/etc/otel", "readOnly": True}]}
    return [
        {"apiVersion": "v1", "kind": "ConfigMap", "metadata": meta("otel-collector", "telemetry"), "data": {"collector.yaml": (ROOT / "collector.yaml").read_text()}},
        {"apiVersion": "v1", "kind": "Service", "metadata": meta("otel-collector", "telemetry"), "spec": {"selector": labels, "ports": [{"name": "grpc", "port": 4317}, {"name": "http", "port": 4318}]}},
        {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": meta("otel-collector", "telemetry"), "spec": {"replicas": 1, "selector": {"matchLabels": labels}, "template": {"metadata": {"labels": dict(OWNER, **labels)}, "spec": {"containers": [container], "volumes": [{"name": "config", "configMap": {"name": "otel-collector"}}]}}}}
    ]
