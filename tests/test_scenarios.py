import json
import shutil
import tempfile
import unittest
from pathlib import Path
from bench.scenarios import catalog, render
from bench.scoring import packet
from helpers import archive


class FullSuiteTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("kubectl"), "kubectl needed for offline kustomize rendering")
    def test_all_scenarios_render_with_custom_registry(self):
        for name, entry in catalog().items():
            with self.subTest(scenario=name):
                out = render(name, "registry.example.test/review", "test-tag")
                self.assertTrue(out.strip())
                self.assertNotIn("fixture.local", out)
                self.assertNotIn("public.ecr.aws", out)
                if name == "multi-fault":
                    self.assertIn("name: report-generator", out)
                    self.assertIn("name: cache-warmer", out)
                if name == "image-pull": self.assertIn("asset-syncer:missing-hotfix", out)

    def test_fullsuite_never_silently_reuses_smoke_truth(self):
        a = archive(); a["suite"] = "full"
        self.assertNotEqual(packet(a)["scenario_truth"]["cause"], packet(archive())["scenario_truth"]["cause"])
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/"truth.json"
            p.write_text(json.dumps({"scenario": "oom", "ground_truth": {"cause": "c", "impact": "i", "mitigation": "m"}}))
            with self.assertRaises(ValueError): packet(a, truth_path=p)
            p.write_text(json.dumps({"scenario": "crashloop", "ground_truth": {"cause": "original workload exits", "impact": "worker unavailable", "mitigation": "repair startup"}}))
            result = packet(a, truth_path=p)
            self.assertEqual(result["scenario_truth"]["cause"], "original workload exits")

    def test_truth_changes_are_hash_visible(self):
        a = archive(); a["suite"] = "full"
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/"truth.json"
            truth = {"scenario": "crashloop", "ground_truth": {"cause": "a", "impact": "b", "mitigation": "c"}}
            p.write_text(json.dumps(truth)); before = packet(a, truth_path=p)
            truth["ground_truth"]["impact"] = "changed"
            p.write_text(json.dumps(truth)); after = packet(a, truth_path=p)
            self.assertNotEqual(before["truth_sha256"], after["truth_sha256"])


if __name__ == "__main__": unittest.main()


class AnswerKeyTests(unittest.TestCase):
    def test_every_full_scenario_scores_with_bundled_truth(self):
        root = Path(__file__).resolve().parents[1]
        for name in catalog():
            with self.subTest(scenario=name):
                a = archive(); a['suite'] = 'full'; a['scenario'] = name
                result = packet(a)
                key = json.loads((root / 'scenarios/faults' / name / 'answer-key.json').read_text())
                self.assertEqual(result['scenario_truth'], key['ground_truth'])
                self.assertEqual(key['scenario'], name)
                for source in key['implementation_sources']:
                    self.assertTrue((root / source).is_file(), source)

    def test_full_and_smoke_multifault_have_distinct_causes(self):
        a = archive(); a['scenario'] = 'multi-fault'
        smoke = packet(a)['scenario_truth']['cause']
        a['suite'] = 'full'
        full = packet(a)['scenario_truth']['cause']
        self.assertIn('Redis', full)
        self.assertNotIn('Redis', smoke)
