FROM golang:1.21 as builder

WORKDIR /build
COPY main.go .
RUN go build main.go

FROM ubuntu:20.04
WORKDIR /home

COPY --from=builder /build/main /home/main