variable "cluster_name" {
  type = string
}

variable "cluster_version" {
  type        = string
  description = "Operator-selected EKS Kubernetes version; verify regional support"
}

variable "node_instance_type" {
  type    = string
  default = "m6i.xlarge"
}

variable "node_count" {
  type        = number
  description = "Initial/steady-state node group size (desired at create; cluster-autoscaler owns it afterwards); the cost model prices this count"
}

variable "node_min" {
  type        = number
  description = "Node group minimum; may sit below the sized baseline so idle clusters shrink"
}

variable "node_max" {
  type        = number
  description = "Node group maximum — bounds burst cost; cost model prices the baseline node_count"
}

variable "node_root_gb" {
  type    = number
  default = 50
}

variable "ebs_target_gb" {
  type        = number
  description = "Documented total EBS cost target incl. future workload PVCs; NOT provisioned here"
}

variable "vpc_cidr" {
  type    = string
  default = "10.42.0.0/16"
}

variable "region" {
  type        = string
  description = "AWS region supplied by the operator"
}

variable "admin_cidrs" {
  type        = list(string)
  description = "CIDRs allowed to use the public API endpoint"
}

variable "addon_versions" {
  type        = map(string)
  description = "Exact compatible add-on versions; generate with scripts/lock_eks_addons.py"
  validation {
    condition     = alltrue([for name in ["vpc-cni", "coredns", "kube-proxy", "eks-pod-identity-agent", "aws-ebs-csi-driver", "eks-node-monitoring-agent", "metrics-server"] : can(regex("^v[0-9]+\\.[0-9]+\\.[0-9]+-eksbuild\\.[0-9]+$", var.addon_versions[name]))])
    error_message = "Provide explicit EKS build versions for all seven add-ons."
  }
}
