ARG GO_VERSION
FROM golang:${GO_VERSION} AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o /clusterloader2 ./cmd/

FROM debian:bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /src /root/perf-tests/clusterloader2
COPY --from=build /clusterloader2 /usr/local/bin/clusterloader2
WORKDIR /root/perf-tests/clusterloader2
ENTRYPOINT ["/usr/local/bin/clusterloader2"]
