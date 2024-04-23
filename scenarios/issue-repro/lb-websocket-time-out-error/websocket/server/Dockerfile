# Use the official Go image as the base image
FROM golang:1.20 as builder

# Set the working directory inside the container
WORKDIR /app

# Copy the source code into the container
COPY . /app

# Build the Go application
RUN go build -o server .

# Expose the necessary port
EXPOSE 8080

# Run the Go application
CMD ["./server"]
