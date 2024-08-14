FROM ubuntu:22.04

RUN apt update && apt install -y libaio1
RUN apt install -y gnupg curl
RUN apt install -y systemd systemd-sysv dbus dbus-user-session

RUN curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc | gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor
RUN echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" | tee /etc/apt/sources.list.d/mongodb-org-7.0.list
RUN apt update
RUN apt install -y mongodb-org
RUN apt install -y openjdk-11-jdk
RUN apt install -y numactl

RUN mkdir -p /data/db
RUN mkdir -p /app
COPY scripts /app/scripts

CMD ["mongod", "--bind_ip", "0.0.0.0", "--replSet", "rs0"]

WORKDIR /app

ENV PATH="/app:${PATH}"
