FROM golang:1.20 as builder

ENV GO111MODULE=on \
    CGO_ENABLED=0 \
    GOOS=linux \
    GOARCH=amd64

WORKDIR /build

COPY https/server .

RUN go build -ldflags="-s -w" -o server .

FROM ubuntu:20.04

WORKDIR /home

COPY --from=builder /build/server /home/server
COPY https/ca.crt /home/ca.crt
COPY https/server.crt /home/server.crt
COPY https/server.csr /home/server.csr
COPY https/server.key /home/server.key

EXPOSE 8080
EXPOSE 4443

ENV READ_HEADER_TIMEOUT="32"
CMD ["./server"]