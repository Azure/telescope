FROM ubuntu:22.04

WORKDIR /home

RUN apt-get update
RUN apt-get install build-essential libssl-dev git unzip -y

RUN git clone https://github.com/wg/wrk.git wrk
WORKDIR /home/wrk
RUN make
RUN cp wrk /usr/local/bin

ENTRYPOINT [ "wrk" ]
