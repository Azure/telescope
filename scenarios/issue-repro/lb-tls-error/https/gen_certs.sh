#!/bin/bash

# Create a self-signed CA certificate and key
openssl req -x509 -new -nodes -keyout ca.key -sha256 -days 3650 -out ca.crt -subj "/C=US/ST=New York/L=New York/O=Example Org/OU=IT Department/CN=example.com"

# Generate a private key for the server
openssl genpkey -algorithm RSA -out server.key

# Create a Certificate Signing Request (CSR) for the server
openssl req -new -key server.key -out server.csr -subj "/C=US/ST=New York/L=New York/O=Example Org/OU=IT Department/CN=server.example.com"

# Sign the server CSR with the CA key, creating a server certificate
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out server.crt -days 365 -sha256

# Generate a private key for the client
openssl genpkey -algorithm RSA -out client.key

# Create a Certificate Signing Request (CSR) for the client
openssl req -new -key client.key -out client.csr -subj "/C=US/ST=New York/L=New York/O=Example Org/OU=IT Department/CN=client.example.com"

# Sign the client CSR with the CA key, creating a client certificate
openssl x509 -req -in client.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out client.crt -days 365 -sha256