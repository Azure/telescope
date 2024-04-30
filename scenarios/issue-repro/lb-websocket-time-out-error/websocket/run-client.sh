#!/bin/bash

./client &> log.txt
code=$?
if [[ $code -eq 0 ]]; then
  websocket_duration_map=$(cat log.txt | grep -o '{.*}')
  websocket_abnormal_closure_count=$(cat log.txt | grep "websocket: close 1006 (abnormal closure)" | wc -l)
  jq --null-input \
    --arg websocket_duration_map "$websocket_duration_map" \
    --arg websocket_abnormal_closure_count "$websocket_abnormal_closure_count" \
    --arg server_address "$SERVER_ADDRESS" \
    --arg server_port "$SERVER_PORT" \
    --arg total_connections "$TOTAL_CONNECTIONS" \
    --arg parallel_connections "$PARALLEL_CONNECTIONS" \
    --arg client_timeout "$CLIENT_TIMEOUT" \
    '{websocket_duration_map: $websocket_duration_map, websocket_abnormal_closure_count: $websocket_abnormal_closure_count,server_address: $server_address, server_port: $server_port, total_connections: $total_connections, parallel_connections: $parallel_connections, client_timeout: $client_timeout}'
else
  echo "Client exited with error"
  cat log.txt
fi
exit $code