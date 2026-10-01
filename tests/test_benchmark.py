import contextlib
import copy
import csv
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bench.__main__ import guard, main
from bench.smoke import NAMESPACE, SCENARIOS, resources
from bench.scoring import packet, validate_archive, validate_judgment


from helpers import archive, judgment


class ScoringTests(unittest.TestCase):
    def test_judge_cannot_fabricate_citation(self):
        p = packet(archive()); j = judgment(p)
        j["final_quality"]["evidence"][0]["quote"] = "Verified recovery"
        with self.assertRaises(ValueError): validate_judgment(j, p)

    def test_judge_cannot_credit_truth_as_product_prose(self):
        p = packet(archive()); j = judgment(p)
        j["final_quality"]["evidence"][0]["source_id"] = "scenario_truth"
        with self.assertRaises(ValueError): validate_judgment(j, p)

    def test_judgment_bound_to_answer_and_policy(self):
        p = packet(archive()); j = judgment(p)
        self.assertEqual(validate_judgment(j, p), j)
        a = archive(); a["sources"]["final_answer"] += " Changed."
        with self.assertRaises(ValueError): validate_judgment(j, packet(a))
        p["rubric_sha256"] = "different"
        with self.assertRaises(ValueError): validate_judgment(j, p)

    def test_missing_trace_cannot_be_claimed_safe(self):
        p = packet(archive()); j = judgment(p)
        j["action_safety"]["verdict"] = "no_unsafe_action_recorded"
        with self.assertRaises(ValueError): validate_judgment(j, p)

    def test_product_metadata_omitted_from_packet(self):
        self.assertNotIn("private-label", json.dumps(packet(archive())))

    def test_missing_final_is_preserved_not_replaced(self):
        a = archive(); a["sources"]["final_answer"] = ""; a["sources"]["intermediate"] = "Good earlier remedy"
        self.assertEqual(packet(a)["sources"]["final_answer"], "")

    def test_detection_not_inferred(self):
        a = archive(); del a["detection"]
        with self.assertRaises(ValueError): validate_archive(a)


    def test_external_adapter_imports_archive(self):
        with tempfile.TemporaryDirectory() as d:
            request = Path(d) / "request.json"; request.write_text(json.dumps(archive()))
            out = Path(d) / "out.json"
            main(["adapter", "--request", str(request), "--out", str(out), "--", sys.executable, "-c", "import sys; print(sys.stdin.read())"])
            self.assertEqual(json.loads(out.read_text()), archive())

    def test_manual_judgment_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            p = packet(archive()); pp = Path(d)/"p.json"; jj = Path(d)/"j.json"; out = Path(d)/"out.json"
            pp.write_text(json.dumps(p)); jj.write_text(json.dumps(judgment(p)))
            main(["judge", "--packet", str(pp), "--manual", str(jj), "--out", str(out)])
            self.assertEqual(json.loads(out.read_text())["final_quality"]["verdict"], "supported")

    def test_detection_comes_from_record_and_summary_counts_undetected(self):
        from bench.reporting import summary, SUMMARY_COLUMNS
        p = packet(archive()); j = judgment(p)
        j['detection'] = {'status': 'detected'}
        result = validate_judgment(j, p)
        self.assertEqual(result['detection']['status'], 'not_measured')
        records = [dict(archive(), detection={'status': value})
                   for value in ['detected', 'not_detected', 'not_measured']]
        rows = [dict(zip(SUMMARY_COLUMNS, row)) for row in summary([result], records)]
        detection = next(row for row in rows if row['dimension'] == 'detection')
        self.assertEqual(detection['eligible'], 2)
        self.assertEqual(detection['success_percent'], 50.0)
        self.assertEqual(detection['not_measured'], 1)
        self.assertEqual(detection['scope'], 'provided_records')
        empty = next(row for row in rows if row['dimension'] == 'causal_change')
        self.assertEqual(empty['success_percent'], '')
        with self.assertRaises(ValueError): list(summary([result, result]))

    def test_product_comparison_and_details_have_matching_denominators(self):
        from bench.reporting import comparison
        records, judgments = [], []
        for product, verdict in [('Product A', 'supported'), ('Product B', 'candidate')]:
            record = archive(); record['product'] = product
            record['detection'] = {'status': 'detected'}
            records.append(record)
            p = packet(record); j = judgment(p); j['final_quality']['verdict'] = verdict
            judgments.append(j)
        missed = archive(); missed['product'] = 'Product A'; missed['case_id'] = 'missed'
        missed['detection'] = {'status': 'not_detected'}; records.append(missed)
        rows = comparison(judgments, records)
        self.assertEqual(rows[0], ['Metric', 'Product A', 'Product B'])
        self.assertIn(['Detection', '1/2 (50.0%)', '1/1 (100.0%)'], rows)
        self.assertIn(['Final mitigation', '1/1 (100.0%)', '0/1 (0.0%)'], rows)
        self.assertIn(['Causal change identification', '—', '—'], rows)
        details = comparison(judgments, records, details=True)
        self.assertIn(['Product A', 'r', 'missed', 'crashloop', 'Detection', 'not_detected', True], details)
        self.assertIn(['Product A', 'r', 'missed', 'crashloop', 'Final mitigation', 'unscored', False], details)
        with self.assertRaises(ValueError): comparison(judgments, records[1:])


class DeploymentTests(unittest.TestCase):
    def test_every_fault_is_namespaced_and_resource_bounded(self):
        for scenario in SCENARIOS:
            manifest = resources(scenario)
            for obj in manifest["items"]:
                if obj["kind"] != "Namespace": self.assertEqual(obj["metadata"]["namespace"], NAMESPACE)
                if obj["kind"] == "Deployment":
                    self.assertEqual(obj["spec"]["replicas"], 1)
                    c = obj["spec"]["template"]["spec"]["containers"][0]
                    self.assertEqual(c["resources"]["limits"]["memory"], "96Mi")
                    self.assertFalse(obj["spec"]["template"]["spec"]["automountServiceAccountToken"])

    def test_reset_removes_both_multifault_changes(self):
        def container(m):
            return next(o for o in m["items"] if o["kind"] == "Deployment")["spec"]["template"]["spec"]["containers"][0]
        fault = container(resources("multi-fault")); baseline = container(resources())
        self.assertEqual(fault["env"][0]["value"], "crash")
        self.assertEqual(fault["readinessProbe"]["httpGet"]["port"], 9090)
        self.assertEqual(baseline["env"][0]["value"], "healthy")
        self.assertEqual(baseline["readinessProbe"]["httpGet"]["port"], 8080)

    def test_refuse_namespace_without_ownership(self):
        with patch("bench.__main__.kubectl", return_value=json.dumps({"metadata": {"labels": {}}})):
            with self.assertRaises(ValueError): guard("explicit-context")

    def test_mutation_requires_explicit_context(self):
        with self.assertRaisesRegex(ValueError, "set context"):
            main(["deploy"])

    def test_render_is_offline(self):
        with patch("bench.__main__.command", side_effect=AssertionError("external call")), patch("builtins.print") as output:
            main(["render", "--scenario", "unbounded-memory"])
            self.assertIn("allocate", output.call_args.args[0])

    def test_cluster_delete_needs_confirmation(self):
        with patch("bench.__main__.command", side_effect=AssertionError("external call")):
            with self.assertRaises(ValueError): main(["cluster", "delete"])


class D6Tests(unittest.TestCase):
    def eligible_packet(self):
        a = archive(); a['suite'] = 'full'
        truth = {'scenario': 'crashloop', 'ground_truth': {'cause': 'startup exits', 'impact': 'worker down', 'mitigation': 'repair startup',
                 'causal_change': {'eligible': True, 'repository': 'fixture', 'introducing_commit': 'a' * 40,
                                  'diff': '+ exit(1)', 'mechanism': 'new unconditional exit',
                                  'access_evidence': 'read check and deployment receipt', 'reviewed_by': 'test reviewer'}}}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'truth.json'; p.write_text(json.dumps(truth))
            return packet(a, truth_path=p)

    def test_ineligible_cannot_receive_credit(self):
        p = packet(archive()); j = judgment(p)
        self.assertEqual(validate_judgment(j, p)['causal_change']['verdict'], 'not_applicable')
        j['causal_change']['verdict'] = 'correct'
        with self.assertRaises(ValueError): validate_judgment(j, p)

    def test_eligible_requires_final_evidence_and_cannot_be_skipped(self):
        p = self.eligible_packet(); j = judgment(p)
        for value in ['correct', 'partial', 'incorrect', 'not_identified', 'not_applicable']:
            j['causal_change']['verdict'] = value
            with self.assertRaises(ValueError): validate_judgment(j, p)
        j['causal_change']['verdict'] = 'not_identified'
        j['causal_change']['evidence'] = [{'source_id': 'final_answer', 'quote': 'API is down.'}]
        validate_judgment(j, p)
        p['sources']['final_answer'] = ''
        j['causal_change']['evidence'] = []
        j['final_quality']['verdict'] = 'insufficient_final_evidence'; j['final_quality']['evidence'] = []
        with self.assertRaises(ValueError): validate_judgment(j, p)
        j['causal_change']['verdict'] = 'insufficient_evidence'
        validate_judgment(j, p)

    def test_eligibility_requires_change_and_access_metadata(self):
        p = self.eligible_packet()
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'truth.json'
            for field in ['repository', 'introducing_commit', 'diff', 'mechanism', 'access_evidence', 'reviewed_by']:
                facts = copy.deepcopy(p['scenario_truth']); del facts['causal_change'][field]
                path.write_text(json.dumps({'scenario': 'crashloop', 'ground_truth': facts}))
                a = archive(); a['suite'] = 'full'
                with self.assertRaises(ValueError): packet(a, truth_path=path)

    def test_legacy_packet_does_not_require_new_dimension(self):
        p = packet(archive()); p['allowed_verdicts'] = dict(p['allowed_verdicts'])
        del p['allowed_verdicts']['causal_change']
        j = judgment(p); j.pop('causal_change', None)
        validate_judgment(j, p)

    def test_summary_excludes_ineligible_but_keeps_missing_evidence(self):
        p = self.eligible_packet()
        with tempfile.TemporaryDirectory() as d:
            paths = []
            for i, verdict in enumerate(['correct', 'insufficient_evidence', 'not_applicable', None]):
                j = judgment(p)
                j['archive_sha256'] = str(i)
                if verdict: j['causal_change']['verdict'] = verdict
                else: del j['causal_change']
                path = Path(d) / f'{i}.json'; path.write_text(json.dumps(j)); paths.append(str(path))
            output = io.StringIO()
            with contextlib.redirect_stdout(output): main(['report', '--summary', *paths])
            row = next(r for r in csv.DictReader(io.StringIO(output.getvalue())) if r['Metric'] == 'Causal change identification')
            self.assertEqual(row['Unspecified product'], '1/2 (50.0%)')
            j['rubric_sha256'] = 'different'; Path(paths[-1]).write_text(json.dumps(j))
            with self.assertRaises(ValueError): main(['report', '--summary', *paths])

if __name__ == "__main__": unittest.main()
