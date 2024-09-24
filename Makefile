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
