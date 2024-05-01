FROM ubuntu:20.04

WORKDIR /home

COPY zombie.c .

RUN apt-get update && apt-get install -y gcc
RUN rm -rf /var/lib/apt/lists/*

RUN gcc -o zombie zombie.c

ENV CHILD_PROCESS_RUNTIME=3600

CMD ./zombie $CHILD_PROCESS_RUNTIME
