.PHONY: build_and_push
build_and_push:
	docker buildx build --platform linux/amd64 -t nlm-ingestor .
	aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 010928228783.dkr.ecr.us-east-1.amazonaws.com
	docker tag nlm-ingestor:latest 010928228783.dkr.ecr.us-east-1.amazonaws.com/nlm-ingestor:latest
	docker push 010928228783.dkr.ecr.us-east-1.amazonaws.com/nlm-ingestor:latest

.PHONY: generate_requirements_from_poetry
generate_requirements_from_poetry:
	poetry export --with dev -f requirements.txt --output requirements.txt

.PHONY: format
format:
	poetry run black .
	poetry run isort .

.PHONY: lint
lint:
	poetry run black --check .
	poetry run isort --check .

.PHONY: run_fmt
run_fmt: format

.PHONY: check
check: lint


# for tests

# Variables
DOCKER_IMAGE_NAME = nlm-ingestor-test
DOCKER_TAG = latest
CONTAINER_NAME = nlm-ingestor-test-container
HOST_PORT = 5010
CONTAINER_PORT = 5001

# TESTING COMMANDS
# Phony targets
.PHONY: all build run test clean run-test-all

# Build the Docker image
build:
	@echo "Building Docker image..."
	docker build -t $(DOCKER_IMAGE_NAME):$(DOCKER_TAG) -f Dockerfile.test .

# Run the Docker container
run:
	@echo "Running Docker container..."
	docker run -d --name $(CONTAINER_NAME) \
		-p $(HOST_PORT):$(CONTAINER_PORT) \
		-v $(PWD)/files:/app/files \
		--add-host=host.docker.internal:host-gateway \
		$(DOCKER_IMAGE_NAME):$(DOCKER_TAG)
	@echo "Waiting for container to start..."
	@sleep 8  # Give the container some time to start up

# Run the tests
test:
	@echo "Running tests..."
	docker exec nlm-ingestor-test-container python /app/tests/run_ingestor_page_test.py

# Clean up
clean:
	@echo "Cleaning up..."
	docker stop $(CONTAINER_NAME) || true
	docker rm $(CONTAINER_NAME) || true
	docker rmi $(DOCKER_IMAGE_NAME):$(DOCKER_TAG) || true

# Run all steps
run-test-all: clean build run test clean