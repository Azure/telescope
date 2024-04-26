FROM golang:1.20 as builder

ENV GO111MODULE=on \
    CGO_ENABLED=0 \
    GOOS=linux \
    GOARCH=amd64

WORKDIR /build

COPY websocket/client .

RUN go build -ldflags="-s -w" -o client .

FROM ubuntu:20.04

RUN apt-get update && apt-get install -y \
    jq \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /home

COPY --from=builder /build/client /home/client
COPY websocket/ca.crt /home/ca.crt
COPY websocket/client.crt /home/client.crt
COPY websocket/client.csr /home/client.csr
COPY websocket/client.key /home/client.key
COPY websocket/run-client.sh .

ENV SERVER_ADDRESS=""
ENV SERVER_PORT="8080"
ENV TOTAL_CONNECTIONS="10000"
ENV PARALLEL_CONNECTIONS="100"
ENV WEBSOCKET_TIMEOUT="240"
CMD ["./run-client.sh"]
