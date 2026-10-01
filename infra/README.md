# AWS EKS setup

This directory is only for AWS EKS. For a local Docker-based cluster, use the [kind setup](../README.md#local-kind); Terraform is not required. “Local state” below describes where Terraform stores its records, not where the cluster runs. All commands below run from the Project Arena root.

The Terraform configuration creates an EKS test cluster with three availability zones, three public and three private subnets, one NAT gateway, managed EKS node group, seven EKS addons including network policy support, EBS CSI, and cluster-autoscaler IAM/discovery resources. Modules are pinned to VPC 6.6.1 and EKS 21.25.0. Default instance type is m6i.xlarge; the example uses three initial nodes, min two/max five and 50 GiB roots. These resources incur AWS charges.

There is no provider profile, account ID, application repository, telemetry vendor or product credential. Credentials come from the AWS SDK credential chain chosen by the operator. Do not copy credentials into `.tfvars`. Required inputs include region, supported Kubernetes version, cluster name and permitted API CIDRs. No Kubernetes version is silently selected on the operator's behalf.

The cluster module enables the public API endpoint restricted to `admin_cidrs`; choose your own routable CIDR. Add-on versions are explicit inputs. Resolve them once with the command below and retain the generated file with your run configuration; later plans reuse those versions. Autoscaler IAM is provisioned; the autoscaler deployment and benchmark workloads are not installed by this root.

## Prerequisites

Install Terraform, a current AWS CLI v2, kubectl, and Docker. Authenticate to your AWS account using your preferred AWS credential setup, then confirm the account and region before creating resources:

```sh
aws sts get-caller-identity
aws eks describe-cluster-versions --region YOUR_REGION \
  --query 'clusterVersions[?status==`STANDARD_SUPPORT`].[clusterVersion,status]' --output table
```

Choose a listed standard-support version for `cluster_version`. If `describe-cluster-versions` is unavailable, update the AWS CLI or check supported versions in the EKS console.

## Local state (default; simplest)

For a test cluster managed by one person from one machine, start here and skip `infra/bootstrap`. Terraform stores its resource records locally; retain the state files so you can update or destroy the cluster later.

```sh
cp infra/cluster/cluster.tfvars.example infra/cluster/local.tfvars
# Edit all YOUR_* placeholders; select a Kubernetes version supported in your region.
python3 scripts/lock_eks_addons.py --region YOUR_REGION --kubernetes-version YOUR_VERSION
terraform -chdir=infra/cluster init
terraform -chdir=infra/cluster validate
terraform -chdir=infra/cluster plan -var-file=local.tfvars -out=cluster.tfplan
# Review the plan, then explicitly apply it if desired:
terraform -chdir=infra/cluster apply cluster.tfplan
aws eks update-kubeconfig --region YOUR_REGION --name YOUR_CLUSTER --alias YOUR_CONTEXT
```

`plan` does not deploy; `apply` does. Protect state/plan files. They are ignored by version control. No bootstrap resources are required for local state.

The version-resolution command only reads AWS's add-on catalog. Use the same region and Kubernetes version as `local.tfvars`; optionally pass `--profile YOUR_PROFILE`. It writes `infra/cluster/addons.auto.tfvars.json`, which Terraform loads automatically. It refuses to overwrite an existing file. For an intentional update, resolve to a separate `--out` file, review the versions, then replace the active file.

## Optional S3 state

Use this option when a team or CI needs to manage the same cluster. Bootstrap creates storage for Terraform’s resource records; it does not create Kubernetes or deploy the benchmark. The S3 bucket shares those records, and the DynamoDB table prevents concurrent Terraform operations from changing the same state.

`infra/bootstrap` creates an operator-named, encrypted, versioned, private S3 state bucket and a DynamoDB lock table. It uses local state, which must be retained outside version control. Both resources have `prevent_destroy`.

```sh
cp infra/bootstrap/bootstrap.tfvars.example infra/bootstrap/local.tfvars
# Set unique bucket/table names and your region.
terraform -chdir=infra/bootstrap init
terraform -chdir=infra/bootstrap plan -var-file=local.tfvars -out=bootstrap.tfplan
terraform -chdir=infra/bootstrap apply bootstrap.tfplan
cp infra/cluster/backend-s3.tf.example infra/cluster/backend.tf
terraform -chdir=infra/cluster init -migrate-state \
  -backend-config=bucket=YOUR_BUCKET -backend-config=key=cluster/terraform.tfstate \
  -backend-config=region=YOUR_REGION -backend-config=dynamodb_table=YOUR_LOCK_TABLE \
  -backend-config=encrypt=true
```

Do not run init migration concurrently with another state writer. The optional backend is operator configuration, not committed account configuration.

## Container registry

Workers must be able to pull the benchmark images. Use a registry you control; create repositories and authenticate Docker before running `build-images --push`. The build command does not provision registry repositories.

For private Amazon ECR in the cluster account, the following creates repositories for every image in the catalog and authenticates Docker. Set these values yourself; the registry/account are not part of the public configuration.

```sh
export ARENA_REGION=YOUR_REGION
export ARENA_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
export ARENA_REGISTRY="$ARENA_ACCOUNT.dkr.ecr.$ARENA_REGION.amazonaws.com"
python3 - <<'PYIMAGES' > /tmp/arena-images.txt
import json
from pathlib import Path
entries = json.loads(Path("scenarios/scenarios.json").read_text()).values()
print("\n".join(sorted({e["image"] for e in entries if "image" in e} | {"shop-app"})))
PYIMAGES
while IFS= read -r image; do
  aws ecr describe-repositories --region "$ARENA_REGION" --repository-names "project-arena/$image" >/dev/null 2>&1 ||
    aws ecr create-repository --region "$ARENA_REGION" --repository-name "project-arena/$image" --image-tag-mutability IMMUTABLE
done < /tmp/arena-images.txt
aws ecr get-login-password --region "$ARENA_REGION" |
  docker login --username AWS --password-stdin "$ARENA_REGISTRY"
python3 -m bench.scenarios build-images --registry "$ARENA_REGISTRY/project-arena" \
  --tag YOUR_UNIQUE_TAG --platform linux/amd64 --push
```

The default `m6i` workers use `linux/amd64`, including when building from an Apple Silicon laptop. Set the same registry prefix and tag in `arena.json` before deployment. Cross-account or other private registries require their own worker pull permissions. Keep `asset-syncer:missing-hotfix` absent: it is an intentional fault. ECR repositories/images persist independently of the cluster; retain them for repeat runs or remove them separately when finished.

## Workloads and teardown

See the [full-suite setup](../scenarios/README.md) for application deployment and fault commands. Install your selected telemetry collector independently. This root does not install Edge Delta or any other vendor.

Before cluster destruction, remove namespace-scoped workload resources and any disposable storage/load-balancer resources they provisioned. Review `terraform plan -destroy -var-file=local.tfvars` before destroying. Bootstrap state storage deliberately persists.
