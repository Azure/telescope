# mcr.microsoft.com/oss/go/microsoft/golang:1.25-azurelinux3.0
FROM mcr.microsoft.com/oss/go/microsoft/golang@sha256:d71fea82e71cb8a9442cb9b8c0afcf71350edf78c239977b57c7aa12d1af1962 AS builder

WORKDIR /workspace

# Copy go mod files
COPY go.mod go.mod
COPY go.sum go.sum

# Cache dependencies
RUN go mod download

# Copy source code
COPY main.go main.go
COPY api/ api/
COPY controllers/ controllers/
COPY pkg/ pkg/

# Build the binary
RUN CGO_ENABLED=1 GOOS=linux GOARCH=amd64 go build -a -ldflags "-s -w" -o datapath-controller main.go

# mcr.microsoft.com/azurelinux/base/core:3.0
FROM mcr.microsoft.com/azurelinux/base/core@sha256:3d53b96f4e336a197023bda703a056eaefecc6728e9a2b0c1ef42f7dce183338

WORKDIR /

# Copy the binary from builder
COPY --from=builder /workspace/datapath-controller .

USER 65532:65532

ENTRYPOINT ["/datapath-controller"]
