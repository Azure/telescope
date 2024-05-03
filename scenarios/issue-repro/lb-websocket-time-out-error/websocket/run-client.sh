#!/bin/bash

./client &> log.txt
code=$?
if [[ $code -eq 0 ]]; then
  echo "client logs:"
  echo "============"
  cat log.txt
  websocket_duration_map=$(cat log.txt | grep -o '{.*}')
  premature_closure_count=$(grep -oE 'Total number of premature closures: [0-9]+' log.txt | cut -d' ' -f6)

  jq --null-input \
    --arg websocket_duration_map "$websocket_duration_map" \
    --arg premature_closure_count "$premature_closure_count" \
    --arg server_address "$SERVER_ADDRESS" \
    --arg server_port "$SERVER_PORT" \
    --arg total_connections "$TOTAL_CONNECTIONS" \
    --arg parallel_connections "$PARALLEL_CONNECTIONS" \
    --arg client_timeout "$CLIENT_TIMEOUT" \
    '{websocket_duration_map: $websocket_duration_map, premature_closure_count: $premature_closure_count,server_address: $server_address, server_port: $server_port, total_connections: $total_connections, parallel_connections: $parallel_connections, client_timeout: $client_timeout}'
else
  echo "Client exited with error"
  cat log.txt
fi
exit $code