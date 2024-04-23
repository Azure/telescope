# Use the official Go image as the base image
FROM golang:1.20 as builder

# Set the working directory inside the container
WORKDIR /app

# Copy the source code into the container
COPY . /app

# Build the Go application
RUN go build -o client

COPY websocket/run-client.sh .

ENV SERVER_ADDRESS=""
ENV SERVER_PORT="8080"
ENV TOTAL_CONNECTIONS="10000"
ENV PARALLEL_CONNECTIONS="100"
ENV WEBSOCKET_TIMEOUT="10"


# Specify the entry point that handles command-line arguments
ENTRYPOINT ["./client"]

# CMD provides default parameter which can be overridden
CMD ["./run-client.sh"]
