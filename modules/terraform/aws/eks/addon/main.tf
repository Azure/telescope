locals {
  policy_arns         = flatten([for addon in var.eks_addon_config_map : addon.policy_arns])
  service_account_map = { for addon in var.eks_addon_config_map : addon.name => addon.service_account if addon.service_account != null }
}

data "aws_iam_openid_connect_provider" "oidc_provider" {
  url = var.cluster_oidc_provider_url
}

data "aws_iam_policy_document" "addon_assume_role_policy" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    effect  = "Allow"

    condition {
      test     = "StringLike"
      variable = "${replace(data.aws_iam_openid_connect_provider.oidc_provider.url, "https://", "")}:aud"
      values   = ["sts.amazonaws.com"]
    }

    dynamic "condition" {
      for_each = local.service_account_map
      content {
        test     = "StringLike"
        variable = "${replace(data.aws_iam_openid_connect_provider.oidc_provider.url, "https://", "")}:sub"
        values   = ["system:serviceaccount:kube-system:${condition.value}"]
      }
    }

    principals {
      identifiers = [data.aws_iam_openid_connect_provider.oidc_provider.arn]
      type        = "Federated"
    }
  }

  depends_on = [data.aws_iam_openid_connect_provider.oidc_provider]
}

resource "aws_iam_role" "addon_role" {
  assume_role_policy = data.aws_iam_policy_document.addon_assume_role_policy.json

  depends_on = [data.aws_iam_policy_document.addon_assume_role_policy]
}

resource "aws_iam_role_policy_attachment" "addon_policy_attachments" {
  for_each = toset(local.policy_arns)

  policy_arn = "arn:aws:iam::aws:policy/${each.value}"
  role       = aws_iam_role.addon_role.name
  depends_on = [aws_iam_role.addon_role]
}

resource "aws_eks_addon" "addon" {
  for_each = var.eks_addon_config_map

  cluster_name             = var.cluster_name
  addon_name               = each.value.name
  addon_version            = each.value.version
  service_account_role_arn = aws_iam_role.addon_role.arn
  configuration_values     = each.value.configuration_values != null ? jsonencode(each.value.configuration_values) : null


  tags = {
    "Name" = each.value.name
  }

  depends_on = [aws_iam_role_policy_attachment.addon_policy_attachments]
}
