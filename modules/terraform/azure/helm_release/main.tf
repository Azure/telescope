resource "helm_release" "vn2" {
  name       = "vn2"
  chart      = "https://shuvstorageaccount.blob.core.windows.net/mycontainer/virtualnode2-0.0.1.tgz?sp=r&st=2024-07-09T11:01:51Z&se=2024-12-30T19:01:51Z&sv=2022-11-02&sr=b&sig=xmtPzHhHxnyaybu62JL0eFOC%2FVNvE6gVD8GBHykkGJU%3D"

  provider = helm
}