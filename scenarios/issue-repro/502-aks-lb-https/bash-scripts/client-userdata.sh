#dowloading kubctl
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl.sha256"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl

#installing helm
curl -fsSL -o get_helm.sh https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3
chmod 700 get_helm.sh
./get_helm.sh


kubectl apply -f tls.yml
kubectl apply -f contoso.yml

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


kubectl get service -n ingress-nginx





