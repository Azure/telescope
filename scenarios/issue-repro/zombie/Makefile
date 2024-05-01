IMAGE_NAME = zombie
IMAGE_REPO=telescope.azurecr.io/issue-repro
DOCKERFILE=Dockerfile
GIT_TAG = $(shell git describe --tags --abbrev=0 2>/dev/null || echo "v0.0.0")

build-and-push-image:
	@echo "Building image..."
	docker build -t ${IMAGE_NAME}:${GIT_TAG} -f $(DOCKERFILE) .
	docker tag ${IMAGE_NAME}:${GIT_TAG} ${IMAGE_REPO}/${IMAGE_NAME}:${GIT_TAG}
	docker push ${IMAGE_REPO}/${IMAGE_NAME}:${GIT_TAG}

