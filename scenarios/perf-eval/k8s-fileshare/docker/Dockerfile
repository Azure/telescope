FROM ubuntu:22.04

RUN apt-get update && apt-get install -y libaio1

WORKDIR /app

COPY fio /app
ENV PATH="/app:${PATH}"
