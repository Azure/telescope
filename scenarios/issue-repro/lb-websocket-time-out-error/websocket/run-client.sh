#!/bin/bash

./client &> log.txt
code=$?
if [[ $code -eq 0 ]]; then
  websocket_duration_json=$(cat log.txt | grep -o '{.*}')
  jq --null-input \
    --arg websocket_duration "$websocket_duration_json" \
    --arg server_address "$SERVER_ADDRESS" \
    --arg server_port "$SERVER_PORT" \
    --arg total_connections "$TOTAL_CONNECTIONS" \
    --arg parallel_connections "$PARALLEL_CONNECTIONS" \
    --arg websocket_timeout "$WEBSOCKET_TIMEOUT" \
    '{error_count: $error_count, server_address: $server_address, server_port: $server_port, total_connections: $total_connections, parallel_connections: $parallel_connections, websocket_timeout: $websocket_timeout}'
else
  echo "Client exited with error"
  cat log.txt
fi
exit $code