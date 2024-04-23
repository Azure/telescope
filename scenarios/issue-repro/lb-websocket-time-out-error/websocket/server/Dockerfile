# Use the official Go image as the base image
FROM golang:1.20 as builder

# Set the working directory inside the container
WORKDIR /app

# Copy the source code into the container
COPY websocket/server /app

# Build the Go application
RUN go build -o server .

COPY websocket/ca.crt /app/ca.crt
COPY websocket/server.crt /app/server.crt
COPY websocket/server.csr /app/server.csr
COPY websocket/server.key /app/server.key

# Expose the necessary port
EXPOSE 8080

# Run the Go application
CMD ["./server"]
