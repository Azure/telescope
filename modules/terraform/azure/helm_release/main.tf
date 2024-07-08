resource "helm_release" "vn2" {
  name       = "vn2"
  chart      = "https://shuvstorageaccount.blob.core.windows.net/mycontainer/virtualnode2-0.0.1.tgz"

  provider = helm
  depends_on = [azurerm_kubernetes_cluster.aks]
}