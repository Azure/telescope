docker run -d --name client -e SERVER_ADDRESS=$public_ip telescope.azurecr.io/issue-repro/slb-eof-error-client:v1.0.5 > /dev/null

code=$(docker wait client)
if [[ $code -eq 0 ]]; then
  tls_count=$(docker logs client | grep "TLS handshake timeout" | wc -l)
  echo "TLS handshake timeout count: $tls_count"
else
  echo "Client exited with error"
fi
exit $code