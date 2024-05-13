FROM golang:1.20 as builder

ENV GO111MODULE=on \
    CGO_ENABLED=0 \
    GOOS=linux \
    GOARCH=amd64

WORKDIR /build

COPY websocket/server .

RUN go build -ldflags="-s -w" -o server .

FROM ubuntu:20.04

RUN apt-get update && apt-get install -y \
    jq \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /home

COPY --from=builder /build/server /home/server
COPY websocket/ca.crt /home/ca.crt
COPY websocket/server.crt /home/server.crt
COPY websocket/server.csr /home/server.csr
COPY websocket/server.key /home/server.key

# Expose the necessary port
EXPOSE 8080
EXPOSE 4443

ENV SERVER_PORT="4443"

# Run the Go application
CMD ["./server"]
