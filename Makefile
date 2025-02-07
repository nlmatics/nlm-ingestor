# Variables
TIKA_JAR = jars/tika-server-standard-nlm-modified-2.9.2_v2.jar
TIKA_PORT = 9998
TIKA_PID_FILE = .tika.pid
DOCKER_IMAGE_NAME = nlm-ingestor-test
DOCKER_TAG = latest
CONTAINER_NAME = nlm-ingestor-test-container
HOST_PORT = 5010
CONTAINER_PORT = 5001

# Development Commands
.PHONY: format lint check run_fmt generate_requirements_from_poetry download_nltk_data
format:
	poetry run black .
	poetry run isort .

lint:
	poetry run black --check .
	poetry run isort --check .

run_fmt: format

check: lint

generate_requirements_from_poetry:
	poetry export --with dev -f requirements.txt --output requirements.txt

download_nltk_data:
	poetry run python -m nltk.downloader punkt stopwords

# Tika Server Commands
.PHONY: start-tika stop-tika check-tika-port kill-existing-tika
check-tika-port:
	@echo "Checking if port $(TIKA_PORT) is in use..."
	@if lsof -i :$(TIKA_PORT) > /dev/null; then \
		echo "Port $(TIKA_PORT) is in use. Killing existing process..."; \
		lsof -ti :$(TIKA_PORT) | xargs kill -9 2>/dev/null || true; \
		sleep 2; \
	fi

kill-existing-tika:
	@echo "Cleaning up any existing Tika processes..."
	@pkill -f "tika-server.*jar" || true
	@rm -f $(TIKA_PID_FILE)
	@sleep 2

start-tika: kill-existing-tika check-tika-port
	@echo "Starting Tika server..."
	@if [ -f $(TIKA_PID_FILE) ]; then \
		echo "Found stale PID file. Removing..."; \
		rm -f $(TIKA_PID_FILE); \
	fi
	@java -jar $(TIKA_JAR) & echo $$! > $(TIKA_PID_FILE)
	@echo "Waiting for Tika server to start..."
	@for i in {1..30}; do \
		if curl -s http://localhost:$(TIKA_PORT)/tika > /dev/null; then \
			echo "Tika server started successfully"; \
			break; \
		fi; \
		if [ $$i -eq 30 ]; then \
			echo "Tika server failed to start"; \
			exit 1; \
		fi; \
		sleep 1; \
	done

stop-tika:
	@echo "Stopping Tika server..."
	@if [ -f $(TIKA_PID_FILE) ]; then \
		kill $$(cat $(TIKA_PID_FILE)) 2>/dev/null || true; \
		rm -f $(TIKA_PID_FILE); \
		echo "Tika server stopped"; \
	else \
		echo "No Tika server PID file found"; \
		pkill -f "tika-server.*jar" || true; \
	fi
	@sleep 2

# Test Commands
.PHONY: test test-pdf-ingestor
test-pdf-ingestor: start-tika
	@echo "Running PDF ingestor tests..."
	PYTHONPATH=. poetry run python tests/run_ingestor_page_test.py
	@make stop-tika

test: start-tika
	@echo "Running all tests..."
	poetry run pytest -vvs .
	@make stop-tika

# Docker Test Commands
.PHONY: build run run-test-all
build:
	@echo "Building Docker image..."
	docker build -t $(DOCKER_IMAGE_NAME):$(DOCKER_TAG) -f Dockerfile.test .

run:
	@echo "Running Docker container..."
	docker run -d --name $(CONTAINER_NAME) \
		-p $(HOST_PORT):$(CONTAINER_PORT) \
		-v $(PWD)/files:/app/files \
		--add-host=host.docker.internal:host-gateway \
		$(DOCKER_IMAGE_NAME):$(DOCKER_TAG)
	@echo "Waiting for container to start..."
	@sleep 8

run-test-all: clean build run test clean

# Deployment Commands
.PHONY: build_and_push
build_and_push:
	docker buildx build --platform linux/amd64 -t pacific-nlm-ingestor .
	aws ecr get-login-password --region us-east-2 | docker login --username AWS --password-stdin 010928228783.dkr.ecr.us-east-2.amazonaws.com
	docker tag pacific-nlm-ingestor:latest 010928228783.dkr.ecr.us-east-2.amazonaws.com/pacific-nlm-ingestor:latest
	docker push 010928228783.dkr.ecr.us-east-2.amazonaws.com/pacific-nlm-ingestor:latest

# Cleanup Commands
.PHONY: clean
clean: stop-tika
	@echo "Cleaning up..."
	rm -f $(TIKA_PID_FILE)
	find . -type d -name "__pycache__" -exec rm -r {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	docker stop $(CONTAINER_NAME) || true
	docker rm $(CONTAINER_NAME) || true
	docker rmi $(DOCKER_IMAGE_NAME):$(DOCKER_TAG) || true