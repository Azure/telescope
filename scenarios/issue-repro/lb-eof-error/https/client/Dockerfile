FROM golang:1.20 as builder

ENV GO111MODULE=on \
    CGO_ENABLED=0 \
    GOOS=linux \
    GOARCH=amd64

WORKDIR /build

COPY https/client .

RUN go build -ldflags="-s -w" -o client .

FROM ubuntu:20.04

WORKDIR /home

COPY --from=builder /build/client /home/client
COPY https/ca.crt /home/ca.crt
COPY https/client.crt /home/client.crt
COPY https/client.csr /home/client.csr
COPY https/client.key /home/client.key

ENV SERVER_ADDRESS=""
ENV SERVER_PORT=""
ENV TOTAL_CONNECTIONS=""
ENV PARALELL_CONNECTIONS=""
ENV TLS_HANDSHAKE_TIMEOUT=""
CMD ["./client", "${SERVER_ADDRESS}", "${SERVER_PORT}", "${TOTAL_CONNECTIONS}", "${PARALELL_CONNECTIONS}", "$TLS_HANDSHAKE_TIMEOUT"]