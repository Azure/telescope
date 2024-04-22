# Use the official Go image as the base image
FROM golang:1.17-alpine

# Set the working directory inside the container
WORKDIR /app

# Copy the source code and module files into the container
COPY go.mod go.sum ./

# Download dependencies if any, if no changes to go.mod and go.sum, Docker cache will be used
RUN go mod download

# Copy the rest of the source code into the container
COPY . .

# Build the Go application
RUN go build -o websocket .

# Expose the necessary port
EXPOSE 8080

# Run the Go application
CMD ["./websocket"]
