FROM ubuntu:22.04

WORKDIR /home

RUN apt-get update
RUN apt-get install build-essential libssl-dev git unzip wget -y


RUN wget https://github.com/wg/wrk/archive/refs/tags/4.2.0.tar.gz
RUN tar -xzvf 4.2.0.tar.gz
WORKDIR /home/wrk-4.2.0
RUN make
RUN cp wrk /usr/local/bin

ENTRYPOINT [ "wrk" ]
