data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  azs = slice(data.aws_availability_zones.available.names, 0, 3)
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "6.6.1"

  name = var.cluster_name
  cidr = var.vpc_cidr

  azs             = local.azs
  private_subnets = [for i in range(3) : cidrsubnet(var.vpc_cidr, 4, i)]
  public_subnets  = [for i in range(3) : cidrsubnet(var.vpc_cidr, 4, i + 8)]

  enable_nat_gateway = true
  single_nat_gateway = true

  enable_dns_hostnames = true
}

data "aws_iam_policy_document" "ebs_csi_assume" {
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession"]

    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ebs_csi" {
  name               = "${var.cluster_name}-ebs-csi"
  assume_role_policy = data.aws_iam_policy_document.ebs_csi_assume.json
}

resource "aws_iam_role_policy_attachment" "ebs_csi" {
  role       = aws_iam_role.ebs_csi.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
}

locals {
  eks_managed_node_groups = {
    default = {
      instance_types             = [var.node_instance_type]
      min_size                   = var.node_min
      max_size                   = var.node_max
      desired_size               = var.node_count
      disk_size                  = var.node_root_gb
      use_custom_launch_template = false
    }
  }
}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "21.25.0"

  name               = var.cluster_name
  kubernetes_version = var.cluster_version

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  endpoint_public_access       = true
  endpoint_public_access_cidrs = var.admin_cidrs

  enable_cluster_creator_admin_permissions = true

  eks_managed_node_groups = local.eks_managed_node_groups

  addons = {
    vpc-cni = {
      addon_version        = var.addon_versions["vpc-cni"]
      before_compute       = true
      configuration_values = jsonencode({ enableNetworkPolicy = "true" })
    }
    coredns = {
      addon_version = var.addon_versions["coredns"]
    }
    kube-proxy = {
      addon_version = var.addon_versions["kube-proxy"]
    }
    eks-pod-identity-agent = {
      addon_version  = var.addon_versions["eks-pod-identity-agent"]
      before_compute = true
    }
    aws-ebs-csi-driver = {
      addon_version = var.addon_versions["aws-ebs-csi-driver"]
      pod_identity_association = [{
        role_arn        = aws_iam_role.ebs_csi.arn
        service_account = "ebs-csi-controller-sa"
      }]
    }
    eks-node-monitoring-agent = {
      addon_version = var.addon_versions["eks-node-monitoring-agent"]
    }
    metrics-server = {
      addon_version = var.addon_versions["metrics-server"]
    }
  }
}


locals {
  cluster_autoscaler_discovery_tags = {
    "k8s.io/cluster-autoscaler/enabled"             = "true"
    "k8s.io/cluster-autoscaler/${var.cluster_name}" = "owned"
  }

  cluster_autoscaler_asg_tag_pairs = merge([
    for ng_key, _ in local.eks_managed_node_groups : {
      for tag_key, tag_value in local.cluster_autoscaler_discovery_tags :
      "${ng_key}|${tag_key}" => {
        ng_key = ng_key
        key    = tag_key
        value  = tag_value
      }
    }
  ]...)
}

resource "aws_autoscaling_group_tag" "cluster_autoscaler" {
  for_each = local.cluster_autoscaler_asg_tag_pairs

  autoscaling_group_name = module.eks.eks_managed_node_groups[each.value.ng_key].node_group_autoscaling_group_names[0]

  tag {
    key                 = each.value.key
    value               = each.value.value
    propagate_at_launch = false
  }
}


data "aws_iam_policy_document" "cluster_autoscaler_assume" {
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession"]

    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "cluster_autoscaler" {
  name               = "${var.cluster_name}-autoscaler"
  assume_role_policy = data.aws_iam_policy_document.cluster_autoscaler_assume.json
}

data "aws_iam_policy_document" "cluster_autoscaler" {
  statement {
    sid    = "ClusterAutoscalerDescribe"
    effect = "Allow"
    actions = [
      "autoscaling:DescribeAutoScalingGroups",
      "autoscaling:DescribeAutoScalingInstances",
      "autoscaling:DescribeLaunchConfigurations",
      "autoscaling:DescribeScalingActivities",
      "autoscaling:DescribeTags",
      "ec2:DescribeInstanceTypes",
      "ec2:DescribeLaunchTemplateVersions",
      "ec2:DescribeImages",
      "ec2:GetInstanceTypesFromInstanceRequirements",
      "eks:DescribeNodegroup",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "ClusterAutoscalerMutate"
    effect = "Allow"
    actions = [
      "autoscaling:SetDesiredCapacity",
      "autoscaling:TerminateInstanceInAutoScalingGroup",
    ]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "autoscaling:ResourceTag/k8s.io/cluster-autoscaler/${var.cluster_name}"
      values   = ["owned"]
    }
  }
}

resource "aws_iam_role_policy" "cluster_autoscaler" {
  name   = "${var.cluster_name}-autoscaler"
  role   = aws_iam_role.cluster_autoscaler.id
  policy = data.aws_iam_policy_document.cluster_autoscaler.json
}

resource "aws_eks_pod_identity_association" "cluster_autoscaler" {
  cluster_name    = module.eks.cluster_name
  namespace       = "kube-system"
  service_account = "cluster-autoscaler"
  role_arn        = aws_iam_role.cluster_autoscaler.arn
}
