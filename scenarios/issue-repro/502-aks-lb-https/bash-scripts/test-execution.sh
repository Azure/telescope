 
 az aks get-credentials -n aks-repro-502 -g repro-502
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



