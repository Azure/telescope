FROM golang:1.22 AS builder
WORKDIR /root
RUN git clone https://github.com/kubernetes/perf-tests.git
RUN cd perf-tests/clusterloader2 && \
    go build -o clusterloader2 ./cmd/

FROM ubuntu:22.04
RUN apt update -y && apt upgrade -y && apt install -y python3 curl
COPY --from=builder /root/perf-tests /root/perf-tests
RUN mkdir $GOPATH/src/k8s.io -p && \
    cp /root/perf-tests $GOPATH/src/k8s.io/perf-tests -r
WORKDIR /root/perf-tests/clusterloader2
ENTRYPOINT ["./clusterloader2"]
