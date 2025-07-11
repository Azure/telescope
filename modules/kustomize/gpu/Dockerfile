# Release notes https://docs.nvidia.com/deeplearning/frameworks/pytorch-release-notes/rel-25-03.html
FROM nvcr.io/nvidia/pytorch:25.03-py3

# NCCL TESTS
ARG NCCL_TESTS_TAG=v2.16.1
# NOTE: GPU Architecture target
ENV A100='-gencode=arch=compute_80,code=sm_80'
ENV H100='-gencode=arch=compute_90,code=sm_90'
WORKDIR /opt/nccl-tests
RUN wget https://github.com/NVIDIA/nccl-tests/archive/${NCCL_TESTS_TAG}.tar.gz
RUN tar --strip-components=1 -xzf ${NCCL_TESTS_TAG}.tar.gz
RUN make -j20 MPI=1 MPI_HOME=/usr/local/mpi/ CUDA_HOME=/usr/local/cuda/ NVCC_GENCODE="${A100} ${H100}"
RUN ln -s /opt/nccl-tests /opt/nccl_tests
RUN ldconfig