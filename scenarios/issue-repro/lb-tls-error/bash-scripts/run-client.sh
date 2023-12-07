docker run -d --name client -e SERVER_ADDRESS=$public_ip -e TOTAL_CONNECTIONS=50000 telescope.azurecr.io/issue-repro/slb-eof-error-client:v1.0.5 > /dev/null

code=$(docker wait client)
if [[ $code -eq 0 ]]; then
  tls_count=$(docker logs client | grep "TLS handshake timeout" | wc -l)
  result=$(jq -n \
    --arg metric "TLS Handshake Timeout" \
    --arg value "$tls_count" \
    --arg unit "times" \
    '{metric: $metric, value: $value, unit: $unit}')
  echo $result
else
  echo "Client exited with error"
fi
docker rm client > /dev/null
exit $code