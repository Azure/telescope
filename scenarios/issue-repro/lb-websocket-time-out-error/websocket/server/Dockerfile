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

# Expose the necessary port
EXPOSE 8080

ENV SERVER_PORT="8080"
ENV SERVER_TIMEOUT="240"

# Run the Go application
CMD ["./server"]
