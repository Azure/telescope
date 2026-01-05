# mcr.microsoft.com/oss/go/microsoft/golang:1.25-azurelinux3.0
FROM mcr.microsoft.com/oss/go/microsoft/golang@sha256:d71fea82e71cb8a9442cb9b8c0afcf71350edf78c239977b57c7aa12d1af1962 AS builder

WORKDIR /app

# Copy go mod files
COPY go.mod go.sum ./

# Download dependencies
RUN go mod download

# Copy source code
COPY main.go ./

# Build binary
RUN CGO_ENABLED=1 GOOS=linux go build -a -ldflags "-s -w" -o reporter main.go

# mcr.microsoft.com/azurelinux/base/core:3.0
FROM mcr.microsoft.com/azurelinux/base/core@sha256:3d53b96f4e336a197023bda703a056eaefecc6728e9a2b0c1ef42f7dce183338

RUN tdnf install -y ca-certificates shadow-utils && tdnf clean all

WORKDIR /root/

# Copy binary from builder
COPY --from=builder /app/reporter .

# Run as non-root user
RUN groupadd -g 1000 reporter && \
    useradd -u 1000 -g reporter -m reporter && \
    chown reporter:reporter reporter

USER reporter

ENTRYPOINT ["./reporter"]
