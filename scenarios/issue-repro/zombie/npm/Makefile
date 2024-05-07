ZOMBIE_IMAGE_NAME=zombie
INIT_IMAGE_NAME=no-zombie
IMAGE_REPO=telescope.azurecr.io/issue-repro
DOCKERFILE=Dockerfile.no-init
INIT_DOCKERFILE=Dockerfile.dumb-init
GIT_TAG=$(shell git describe --tags --abbrev=0 2>/dev/null || echo "v0.0.0")

.PHONY: all build-and-push-zombie-image build-and-push-init-image

all: build-and-push-zombie-image build-and-push-init-image

build-and-push-zombie-image:
	@echo "Building zombie image..."
	docker build -t ${ZOMBIE_IMAGE_NAME}:${GIT_TAG} -f ${DOCKERFILE} .
	docker tag ${ZOMBIE_IMAGE_NAME}:${GIT_TAG} ${IMAGE_REPO}/${ZOMBIE_IMAGE_NAME}:${GIT_TAG}
	docker push ${IMAGE_REPO}/${ZOMBIE_IMAGE_NAME}:${GIT_TAG}

build-and-push-init-image:
	@echo "Building init image..."
	docker build -t ${INIT_IMAGE_NAME}:${GIT_TAG} -f ${INIT_DOCKERFILE} .
	docker tag ${INIT_IMAGE_NAME}:${GIT_TAG} ${IMAGE_REPO}/${INIT_IMAGE_NAME}:${GIT_TAG}
	docker push ${IMAGE_REPO}/${INIT_IMAGE_NAME}:${GIT_TAG}

