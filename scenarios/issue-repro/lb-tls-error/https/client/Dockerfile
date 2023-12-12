FROM golang:1.20 as builder

ENV GO111MODULE=on \
    CGO_ENABLED=0 \
    GOOS=linux \
    GOARCH=amd64

WORKDIR /build

COPY https/client .

RUN go build -ldflags="-s -w" -o client .

FROM ubuntu:20.04

RUN apt-get update && apt-get install -y \
    jq \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /home

COPY --from=builder /build/client /home/client
COPY https/ca.crt /home/ca.crt
COPY https/client.crt /home/client.crt
COPY https/client.csr /home/client.csr
COPY https/client.key /home/client.key
COPY https/run-client.sh .

ENV SERVER_ADDRESS=""
ENV SERVER_PORT="443"
ENV TOTAL_CONNECTIONS="1000000"
ENV PARALELL_CONNECTIONS="100"
ENV TLS_HANDSHAKE_TIMEOUT="10"
ENV DISALBE_KEEP_ALIVES="false"
CMD ["./run-client.sh"]