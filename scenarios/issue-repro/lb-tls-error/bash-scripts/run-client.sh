docker run -d --name client -e SERVER_ADDRESS=$public_ip telescope.azurecr.io/issue-repro/slb-eof-error-client:v1.0.5 > /dev/null
docker wait client