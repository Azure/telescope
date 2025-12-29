# Build stage
FROM golang:1.25-alpine AS builder

WORKDIR /app

# Copy go mod files
COPY go.mod go.sum ./

# Download dependencies
RUN go mod download

# Copy source code
COPY main.go ./

# Build binary
RUN CGO_ENABLED=0 GOOS=linux go build -o reporter main.go

# Final stage
FROM alpine:latest

RUN apk --no-cache add ca-certificates

WORKDIR /root/

# Copy binary from builder
COPY --from=builder /app/reporter .

# Run as non-root user
RUN addgroup -g 1000 reporter && \
    adduser -D -u 1000 -G reporter reporter && \
    chown reporter:reporter reporter

USER reporter

ENTRYPOINT ["./reporter"]
