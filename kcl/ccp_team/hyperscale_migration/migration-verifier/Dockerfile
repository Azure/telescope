# syntax=docker/dockerfile:1.7

FROM golang:1.24.6-bookworm AS build
WORKDIR /src

COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN go test ./...

ARG VERSION=dev
ARG COMMIT=unknown
ARG TARGETOS=linux
ARG TARGETARCH=amd64
RUN test "$TARGETOS" = "linux" && test "$TARGETARCH" = "amd64" && \
    CGO_ENABLED=0 GOOS="$TARGETOS" GOARCH="$TARGETARCH" \
    go build -trimpath \
      -ldflags="-s -w -X main.version=$VERSION -X main.commit=$COMMIT" \
      -o /out/hyperscale-migration-verifier ./cmd

FROM scratch
    COPY --from=build /out/hyperscale-migration-verifier /usr/local/bin/hyperscale-migration-verifier
    ENTRYPOINT ["/usr/local/bin/hyperscale-migration-verifier"]
