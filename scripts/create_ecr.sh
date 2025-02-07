#!/bin/bash

# Variables
REPO_NAME=$1
REGION=${2:-us-east-2} # Default region is us-east-1 if not provided

# Check if repository name is passed
if [ -z "$REPO_NAME" ]; then
  echo "Usage: ./create_ecr_repo.sh <repository_name> [region]"
  exit 1
fi

# Create ECR repository
echo "Creating ECR repository: $REPO_NAME in region: $REGION"

aws ecr create-repository \
    --repository-name "$REPO_NAME" \
    --region "$REGION" \
    --image-scanning-configuration scanOnPush=true \
    --encryption-configuration encryptionType=AES256

# Check if the repository creation was successful
if [ $? -eq 0 ]; then
  echo "ECR repository '$REPO_NAME' created successfully in region '$REGION'."
else
  echo "Failed to create ECR repository."
  exit 1
fi