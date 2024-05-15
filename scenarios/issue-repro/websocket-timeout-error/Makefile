BASE_DIR := websocket

SERVER_DIR := $(BASE_DIR)/server
CLIENT_DIR := $(BASE_DIR)/client
SERVER_IMAGE_NAME = websocket-server
CLIENT_IMAGE_NAME = websocket-client
SERVER_DOCKERFILE = $(SERVER_DIR)/Dockerfile
CLIENT_DOCKERFILE = $(CLIENT_DIR)/Dockerfile
GIT_TAG = v1.2.2
IMAGE_REPO = telescope.azurecr.io/issue-repro

.PHONY: all build-server push-server build-client push-client release

all: build-server build-client release

gen-certs:
	@echo "Generating certificates..."
	@(cd $(BASE_DIR) && ./gen-certs.sh)

clean-certs:
	@echo "Cleaning certs..."
	@rm -f $(BASE_DIR)/ca.* $(BASE_DIR)/*.csr $(BASE_DIR)/*.crt $(BASE_DIR)/*.key

build-server:
	@echo "Building server..."
	docker build -t $(SERVER_IMAGE_NAME):${GIT_TAG} -f $(SERVER_DOCKERFILE) .

push-server: build-server
	@echo "Pushing server..."
	docker tag $(SERVER_IMAGE_NAME):${GIT_TAG} $(IMAGE_REPO)/$(SERVER_IMAGE_NAME):$(GIT_TAG)
	docker push $(IMAGE_REPO)/$(SERVER_IMAGE_NAME):$(GIT_TAG)

build-client:
	@echo "Building client..."
	docker build -t $(CLIENT_IMAGE_NAME):${GIT_TAG} -f $(CLIENT_DOCKERFILE) .

push-client: build-client
	@echo "Pushing client..."
	docker tag $(CLIENT_IMAGE_NAME):${GIT_TAG} $(IMAGE_REPO)/$(CLIENT_IMAGE_NAME):$(GIT_TAG)
	docker push $(IMAGE_REPO)/$(CLIENT_IMAGE_NAME):$(GIT_TAG)

release: push-server push-client
	@echo "Release finished"