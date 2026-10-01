import importlib.util
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch
from bench.app_manifests import resources, flag_config, FLAG_FAULTS
from bench.cluster_ops import check, fault_objects, guard, reset, deploy

def lookup(objects, kind, name, ns=None):
    return next(o for o in objects if o["kind"] == kind and o["metadata"]["name"] == name and (ns is None or o["metadata"].get("namespace") == ns))


class TopologyTests(unittest.TestCase):
    def setUp(self): self.objects = resources("TEST_ADMIN", "TEST_APPLICATION")["items"]

    @unittest.skipUnless(shutil.which("kubectl"), "kubectl required to render fault manifests")
    def test_database_jobs_and_app_use_matching_credentials(self):
        admin = lookup(self.objects, "Secret", "db-maintenance", "batch")["stringData"]
        db = lookup(self.objects, "Secret", "postgres", "datastore")["stringData"]
        catalog = lookup(self.objects, "Deployment", "product-catalog", "shop")
        env = {e["name"]: e.get("value") for e in catalog["spec"]["template"]["spec"]["containers"][0]["env"]}
        self.assertEqual(admin["PGUSER"], "shop")
        self.assertEqual(admin["PGPASSWORD"], db["POSTGRES_PASSWORD"])
        self.assertIn("shop_user:TEST_APPLICATION@postgres.datastore", env["DB_CONNECTION_STRING"])
        sql = lookup(self.objects, "ConfigMap", "postgres-init")["data"]["init.sql"]
        self.assertIn("CREATE TABLE catalog.products", sql)
        self.assertIn("'TEST_APPLICATION'", sql)
        self.assertNotIn("'shop_password'", sql)
        consumer = {"PGDATABASE": "shop_db", "PGHOST": "postgres.datastore.svc.cluster.local"}
        for scenario in ["pg-lock-hold", "stale-db-credentials"]:
            job = fault_objects(scenario, "fixture.local", "v1")[0]
            env = {e["name"]: e for e in job["spec"]["template"]["spec"]["containers"][0]["env"]}
            self.assertEqual(env["PGDATABASE"]["value"], consumer["PGDATABASE"])
            self.assertEqual(env["PGHOST"]["value"], consumer["PGHOST"])
            for name in ["PGUSER", "PGPASSWORD"]:
                self.assertEqual(env[name]["valueFrom"]["secretKeyRef"], {"name": "db-maintenance", "key": name})

    @unittest.skipUnless(shutil.which("kubectl"), "kubectl required to render fault manifests")
    def test_quota_fault_survives_kubernetes_request_defaulting(self):
        r = lookup(self.objects, "Deployment", "recommendation", "shop")["spec"]["template"]["spec"]["containers"][0]["resources"]
        self.assertNotIn("cpu", r.get("requests", {}))
        self.assertNotIn("cpu", r["limits"])
        self.assertIn("requests.cpu", fault_objects("quota-trap", "fixture.local", "v1")[0]["spec"]["hard"])

    @unittest.skipUnless(shutil.which("kubectl"), "kubectl required to render fault manifests")
    def test_network_policy_selects_actual_cart_pod(self):
        policy = fault_objects("netpol-isolation", "fixture.local", "v1")[0]
        labels = lookup(self.objects, "Deployment", "cart", "shop")["spec"]["template"]["metadata"]["labels"]
        self.assertTrue(all(labels[k] == v for k, v in policy["spec"]["podSelector"]["matchLabels"].items()))

    @unittest.skipUnless(shutil.which("kubectl"), "kubectl required to render fault manifests")
    def test_flags_reset_and_only_named_fault_is_enabled(self):
        baseline = json.loads(flag_config()["data"]["flags.json"])["flags"]
        for scenario, (key, variant) in FLAG_FAULTS.items():
            values = json.loads(fault_objects(scenario, "fixture.local", "v1")[0]["data"]["flags.json"])["flags"]
            self.assertEqual(values[key]["defaultVariant"], variant)
            self.assertEqual([k for k in values if values[k] != baseline[k]], [key])
        self.assertEqual(baseline["browseJourneyConcurrency"]["defaultVariant"], "5")

    def test_original_database_and_redis_persistent_storage(self):
        for name in ["postgres", "redis"]:
            obj = lookup(self.objects, "StatefulSet", name, "datastore")
            self.assertEqual(obj["spec"]["volumeClaimTemplates"][0]["spec"]["resources"]["requests"]["storage"], "100Gi")

    def test_all_service_selectors_match_pods(self):
        for svc in [o for o in self.objects if o["kind"] == "Service"]:
            dep = lookup(self.objects, "StatefulSet" if svc["metadata"]["name"] in ["postgres", "redis"] else "Deployment", svc["metadata"]["name"], svc["metadata"]["namespace"])
            self.assertTrue(all(dep["spec"]["template"]["metadata"]["labels"].get(k) == v for k, v in svc["spec"]["selector"].items()))


class OperationalTests(unittest.TestCase):
    def test_arm_only_cluster_rejected_before_mutation(self):
        nodes = {"items": [{"metadata": {"labels": {"kubernetes.io/arch": "arm64"}}}]}
        with patch("bench.cluster_ops.kube", return_value=json.dumps(nodes)) as kube:
            with self.assertRaisesRegex(ValueError, "AMD64"):
                deploy("context", "fixture.local", "v1")
        self.assertEqual(kube.call_count, 1)

    def test_unowned_namespace_blocks_mutation(self):
        with patch("bench.cluster_ops.obj", return_value={"metadata": {"labels": {}}}):
            with self.assertRaises(ValueError): guard("context", False)

    def test_reset_requires_explicit_scope_confirmation(self):
        with patch("bench.cluster_ops.kube", side_effect=AssertionError("must not run")):
            with self.assertRaises(ValueError): reset("context", False)

    def test_generic_outage_does_not_confirm_specific_fault(self):
        self.assertFalse(check("pg-lock-hold", {"http": {"status": 503, "body": "timed out"}}))
        self.assertTrue(check("pg-lock-hold", {"exclusive_locks": 1, "lock_waiters": 1}))
        self.assertFalse(check("payment-failure", {"http": {"status": 503, "body": "unrelated outage"}}))
        self.assertFalse(check("traffic-flood", {"requests_per_second": 1.2}))
        self.assertFalse(check("traffic-flood", {"requests_per_second": 10}))
        self.assertTrue(check("traffic-flood", {"application_logs": {"load-generator": "concurrency flag changed (5 -> 50), restarting k6"}}))

    def test_multifault_requires_both_causes(self):
        e = {"batch": [{"kind": "Pod", "status": {"containerStatuses": [{"state": {"waiting": {"reason": "CrashLoopBackOff"}}}]}}], "logs": ""}
        self.assertFalse(check("multi-fault", e))
        e["logs"] = "write rejected (OOM)"; self.assertTrue(check("multi-fault", e))

    def test_reset_releases_pvc_before_deleting_owned_pv(self):
        owned_resource = {"metadata": {"labels": {"portable-benchmark": "suite-v1"}}}
        with patch("bench.cluster_ops.guard"), patch("bench.cluster_ops.state", return_value={"registry": "fixture.local", "tag": "v1"}), patch("bench.cluster_ops.obj", return_value=owned_resource), patch("bench.cluster_ops.kube") as kube, patch("bench.cluster_ops.deploy", return_value={"observed": True}):
            reset("explicit", True)
        calls = [c.args for c in kube.call_args_list]
        self.assertEqual(calls[0][2], "ValidatingWebhookConfiguration")
        self.assertEqual(calls[1][2], "namespace")
        self.assertEqual(calls[2][2], "PersistentVolume")



if __name__ == "__main__": unittest.main()
