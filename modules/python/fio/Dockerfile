FROM mcr.microsoft.com/azurelinux/base/core:3.0

# Install dependencies required for building FIO
RUN tdnf update -y
RUN tdnf install -y build-essential git openssl-devel ca-certificates tar wget util-linux \
    libaio-devel zlib-devel librdmacm-devel libibverbs-devel libnuma-devel python3-devel

# Download and build FIO 3.40
WORKDIR /tmp
RUN wget https://github.com/axboe/fio/archive/refs/tags/fio-3.40.tar.gz
RUN tar -xzf fio-3.40.tar.gz
WORKDIR /tmp/fio-fio-3.40
RUN ./configure
RUN make
RUN make install