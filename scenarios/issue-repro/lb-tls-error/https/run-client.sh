#!/bin/bash

./client &> log.txt
code=$?
if [[ $code -eq 0 ]]; then
  error_count=$(cat log.txt | grep "TLS handshake timeout" | wc -l)
  jq --null-input \
    --arg error_count "$error_count" \
    --arg server_address "$SERVER_ADDRESS" \
    --arg server_port "$SERVER_PORT" \
    --arg total_connections "$TOTAL_CONNECTIONS" \
    --arg parallel_connections "$PARALELL_CONNECTIONS" \
    --arg tls_handshake_timeout "$TLS_HANDSHAKE_TIMEOUT" \
    --arg disable_keep_alives "$DISALBE_KEEP_ALIVES" \
    '{error_count: $error_count, server_address: $server_address, server_port: $server_port, total_connections: $total_connections, parallel_connections: $parallel_connections, tls_handshake_timeout: $tls_handshake_timeout, disable_keep_alives: $disable_keep_alives}'
else
  echo "Client exited with error"
  cat log.txt
fi
exit $code