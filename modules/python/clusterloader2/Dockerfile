FROM mcr.microsoft.com/cbl-mariner/base/core:2.0 AS builder
RUN tdnf update -y && \
    tdnf install -y git go ca-certificates gcc glibc-devel binutils kernel-headers
WORKDIR /root
RUN git clone https://github.com/Azure/perf-tests.git
RUN cd perf-tests/clusterloader2 && \
    go build -o clusterloader2 ./cmd/

FROM mcr.microsoft.com/cbl-mariner/base/core:2.0
RUN tdnf update -y && \
    tdnf install -y curl unzip ca-certificates
RUN curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" \
    && unzip awscliv2.zip \
    && ./aws/install \
    && rm -rf awscliv2.zip aws
COPY --from=builder /root/perf-tests /root/perf-tests
RUN mkdir $GOPATH/src/k8s.io -p && \
    cp /root/perf-tests $GOPATH/src/k8s.io/perf-tests -r
WORKDIR /root/perf-tests/clusterloader2
ENTRYPOINT ["./clusterloader2"]
