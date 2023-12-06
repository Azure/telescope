#dowloading kubctl
curl -LO https://storage.googleapis.com/kubernetes-release/release/$(curl -s https://storage.googleapis.com/kubernetes-release/release/stable.txt)/bin/linux/amd64/kubectl
chmod +x ./kubectl
sudo mv ./kubectl /usr/local/bin/kubectl


#installing helm
curl -fsSL -o get_helm.sh https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3
chmod 700 get_helm.sh
./get_helm.sh


kubectl apply -f nginxCert.yml
kubectl apply -f aksSetup.yml

helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm upgrade --install prometheus prometheus-community/prometheus
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --set controller.service.externalTrafficPolicy=Local \
  --set controller.service.ports.https=443 \
  --set controller.replicaCount=3 \
  --set controller.service.loadBalancerIP=10.10.1.250 \
  --set controller.service.annotations."service\.beta\.kubernetes\.io/azure-load-balancer-internal"=true \
  --set controller.service.annotations."service\.beta\.kubernetes\.io/azure-load-balancer-internal-subnet"="AksSubnet" \
  --set controller.extraArgs.default-ssl-certificate="ingress-nginx/ingress-tls" \
  --set controller.admissionWebhooks.enabled=false


result=$(kubectl get service -n ingress-nginx)
regex="80:([0-9]+).*443:([0-9]+)"
 [[ $result =~ $regex ]]
httpPort=${BASH_REMATCH[1]}
httpsPort=${BASH_REMATCH[1]}







