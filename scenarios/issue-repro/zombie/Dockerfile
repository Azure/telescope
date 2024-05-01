FROM gcc:latest

WORKDIR /home

COPY zombie.c .

RUN gcc -o zombie zombie.c

ENV SLEEP_TIME=60

CMD ./zombie $SLEEP_TIME
