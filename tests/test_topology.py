import importlib.util
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch
from bench.app_manifests import resources, flag_config, FLAG_FAULTS
from bench.cluster_ops import check, fault_objects, guard, reset, deploy
from bench import retirement

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
        with patch("bench.cluster_ops.require_direct"), patch("bench.cluster_ops.kube", return_value=json.dumps(nodes)) as kube:
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

    def test_crashloop_detects_repeated_crashes_between_backoff_windows(self):
        pod = {"kind": "Pod", "metadata": {"name": "report-generator-test"}, "status": {"containerStatuses": [{"state": {"running": {}}, "restartCount": 3, "lastState": {"terminated": {"exitCode": 1}}}]}}
        backoff = {"kind": "Event", "reason": "BackOff", "involvedObject": {"name": "report-generator-test"}}
        self.assertTrue(check("crashloop", {"batch": [pod, backoff]}))
        self.assertFalse(check("crashloop", {"batch": [pod]}))
        pod["metadata"]["name"] = "unrelated-app"
        self.assertFalse(check("crashloop", {"batch": [pod, backoff]}))

    def test_multifault_requires_both_causes(self):
        e = {"batch": [{"kind": "Pod", "metadata": {"name": "report-generator-test"}, "status": {"containerStatuses": [{"state": {"waiting": {"reason": "CrashLoopBackOff"}}}]}}], "logs": ""}
        self.assertFalse(check("multi-fault", e))
        e["logs"] = "write rejected (OOM)"; self.assertTrue(check("multi-fault", e))

    def test_reset_preserves_application_and_retires_only_fault_resources(self):
        fault = [{"apiVersion": "v1", "kind": "PersistentVolumeClaim", "metadata": {"name": "index-store", "namespace": "batch"}},
                 {"apiVersion": "v1", "kind": "PersistentVolume", "metadata": {"name": "index-store"}}]
        def obj(context, kind, name, namespace=None):
            return flag_config() if name == 'flagd-config' else {"metadata": {"labels": {"portable-benchmark": "suite-v1"}}}
        with patch('bench.cluster_ops.require_direct'), patch('bench.cluster_ops.guard'), patch('bench.cluster_ops.state', return_value={'registry': 'fixture.local', 'tag': 'v1', 'scenario': 'volume-affinity-conflict'}), patch('bench.cluster_ops.obj', side_effect=obj), patch('bench.cluster_ops.fault_objects', return_value=fault), patch('bench.cluster_ops.kube') as kube, patch('bench.cluster_ops.set_state') as state, patch('bench.cluster_ops.verify', return_value={'observed': True}), patch.object(retirement, 'wait_pruned'), patch.object(retirement, 'restore', return_value=[]) as restore, patch.object(retirement, 'wait_baseline', return_value={'passed': True}):
            reset('context', True)
        deleted = json.loads(kube.call_args.kwargs['stdin'])['items']
        self.assertEqual([o['kind'] for o in deleted], ['PersistentVolumeClaim'])
        self.assertTrue(state.call_args_list[0].kwargs['reset_pending'])
        self.assertEqual(state.call_args_list[-1].args, ('context', 'fixture.local', 'v1'))
        restore.assert_called_once_with('context', 'volume-affinity-conflict')


class RetirementTests(unittest.TestCase):
    def test_admission_recovery_allows_controller_backoff_without_mutation(self):
        for scenario in ('quota-trap', 'admission-webhook-outage', 'crashloop'):
            with self.subTest(scenario=scenario), patch.object(retirement, 'baseline_failures', side_effect=[['recommendation is not 1/1 available'], []]), patch.object(retirement.time, 'monotonic', side_effect=[0, 200]), patch.object(retirement.time, 'sleep'), patch.object(retirement.cluster, 'kube') as kube:
                if scenario == 'crashloop':
                    with self.assertRaisesRegex(ValueError, 'wait expired; recovery is not yet confirmed'):
                        retirement.wait_baseline('ctx', retirement.recovery_timeout(scenario))
                else:
                    self.assertTrue(retirement.wait_baseline('ctx', retirement.recovery_timeout(scenario))['passed'])
                kube.assert_not_called()

    def test_cleanup_is_scenario_specific_and_redis_order_matches_parent(self):
        with patch('bench.retirement.cluster.kube') as kube, patch.object(retirement, 'psql') as psql:
            self.assertEqual(retirement.restore('ctx', ''), [])
            self.assertEqual(retirement.restore('ctx', 'crashloop'), [])
            kube.assert_not_called(); psql.assert_not_called()
            retirement.restore('ctx', 'redis-pressure')
        calls = kube.call_args_list
        self.assertEqual(calls[0].args[-4:], ('config', 'set', 'maxmemory', '256mb'))
        self.assertIn('warm:*', calls[1].args[-1])
        self.assertNotIn('FLUSH', calls[1].args[-1])
        with patch('bench.retirement.cluster.kube', side_effect=RuntimeError('restore failed')) as kube:
            with self.assertRaises(RuntimeError): retirement.restore('ctx', 'redis-pressure')
            self.assertEqual(kube.call_count, 1)

    def test_password_comes_from_actual_consumer_secret_and_stays_off_argv(self):
        import base64
        dep = {'spec': {'template': {'spec': {'containers': [{'name': 'product-catalog', 'env': [{'name': 'DB_CONNECTION_STRING', 'valueFrom': {'secretKeyRef': {'name': 'rotated-client-setting', 'key': 'url'}}}]}]}}}}
        secret = {'data': {'url': base64.b64encode(b'postgres://shop_user:new%27password@postgres/shop_db').decode()}}
        with patch('bench.retirement.cluster.obj', side_effect=[dep, secret]) as obj, patch.object(retirement, 'psql') as psql:
            retirement.restore('ctx', 'stale-db-credentials')
        self.assertEqual(obj.call_args.args[2], 'rotated-client-setting')
        self.assertIn("new''password", psql.call_args.args[1])
        with patch('bench.retirement.cluster.kube', return_value='') as kube:
            retirement.psql('ctx', 'PRIVATE_SQL')
        self.assertNotIn('PRIVATE_SQL', kube.call_args.args)
        self.assertEqual(kube.call_args.kwargs['stdin'], 'PRIVATE_SQL\n')

    def test_lock_cleanup_matches_table_lock_not_query_text(self):
        with patch.object(retirement, 'psql', side_effect=['1', '1', '0']) as psql:
            retirement.restore('ctx', 'pg-lock-hold')
        query = psql.call_args_list[1].args[1]
        self.assertIn("catalog.products", query)
        self.assertIn('pg_terminate_backend', query)
        self.assertNotIn('LIKE', query)
        self.assertIn('a.pid<>pg_backend_pid()', query)

    def test_baseline_checks_report_residual_faults_even_with_healthy_http(self):
        def kube(*args, **kwargs):
            if retirement.BATCH_RESOURCES in args: return '{"items": [{"kind": "PersistentVolumeClaim"}]}'
            if 'resourcequotas,networkpolicies' in args: return '{"items": [{"kind": "ResourceQuota"}]}'
            if 'maxmemory' in args: return 'maxmemory\n134217728\n'
            if 'logs' in args: return 'password authentication failed for user shop_user'
            return 'warm:remaining'
        def obj(context, kind, name, namespace=None):
            if name == 'flagd-config': return flag_config()
            if kind == 'deployment': return {'status': {'availableReplicas': 0}}
            return {'metadata': {'name': name}}
        with patch('bench.retirement.cluster.kube', side_effect=kube), patch('bench.retirement.cluster.obj', side_effect=obj), patch.object(retirement, 'psql', return_value='1'):
            failures = retirement.baseline_failures('ctx')
        for expected in ['batch workloads or claims remain', 'shop quota or network policy remains', 'Redis maxmemory is not 256mb', 'Redis warm:* keys remain', 'granted exclusive locks remain', 'recommendation is not 1/1 available']:
            self.assertIn(expected, failures)
        self.assertTrue(any('pod-policy' in value for value in failures))
        self.assertTrue(any('index-store' in value for value in failures))
        self.assertTrue(any('authentication failures' in value for value in failures))

    def test_flag_edits_preserve_unrelated_flag_settings(self):
        current = flag_config()
        body = json.loads(current['data']['flags.json'])
        body['flags']['adServeFallback']['defaultVariant'] = 'on'
        current['data']['flags.json'] = json.dumps(body)
        changed = retirement.flags(current, 'payment-failure')
        values = json.loads(changed['data']['flags.json'])['flags']
        self.assertEqual(values['paymentStrictTokenCheck']['defaultVariant'], '100%')
        self.assertEqual(values['adServeFallback']['defaultVariant'], 'on')
        reset = json.loads(retirement.flags(changed)['data']['flags.json'])['flags']
        self.assertEqual(reset['paymentStrictTokenCheck']['defaultVariant'], 'off')
        self.assertEqual(reset['adServeFallback']['defaultVariant'], 'on')
        self.assertEqual(json.loads(retirement.flags(current, 'oom')['data']['flags.json']), body)




if __name__ == "__main__": unittest.main()
