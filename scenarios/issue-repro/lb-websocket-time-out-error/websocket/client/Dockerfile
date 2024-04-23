# Use the official Go image as the base image
FROM golang:1.20 as builder

# Set the working directory inside the container
WORKDIR /app

# Copy the source code into the container
COPY . /app

# Build the Go application
RUN go build -o client

# Specify the entry point that handles command-line arguments
ENTRYPOINT ["./client"]

# CMD provides default parameter which can be overridden
CMD ["localhost"]
