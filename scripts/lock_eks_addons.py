"""Resolve EKS add-on defaults once and write explicit Terraform version inputs."""
import argparse
import json
import subprocess
from pathlib import Path

ADDONS = ['vpc-cni', 'coredns', 'kube-proxy', 'eks-pod-identity-agent', 'aws-ebs-csi-driver', 'eks-node-monitoring-agent', 'metrics-server']
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--region', required=True)
p.add_argument('--kubernetes-version', required=True)
p.add_argument('--profile')
p.add_argument('--out', default='infra/cluster/addons.auto.tfvars.json')
a = p.parse_args()
if Path(a.out).exists(): raise SystemExit('Output exists; choose a new --out to review an update.')
versions = {}
for name in ADDONS:
    cmd = ['aws', '--region', a.region, *(['--profile', a.profile] if a.profile else []), 'eks', 'describe-addon-versions', '--addon-name', name, '--kubernetes-version', a.kubernetes_version, '--output', 'json']
    data = json.loads(subprocess.check_output(cmd, text=True))
    candidates = [v for addon in data['addons'] for v in addon['addonVersions'] if any(c.get('defaultVersion') for c in v.get('compatibilities', []))]
    if not candidates: raise SystemExit('No compatible default version returned for ' + name)
    versions[name] = candidates[0]['addonVersion']
with Path(a.out).open('x') as f: json.dump({'addon_versions': versions}, f, indent=2); f.write('\n')
print('Saved exact add-on versions to', a.out)
