#!/bin/bash

profile=$1

if [ -z "$profile" ]; then
    echo "Current AWS_PROFILE: $AWS_PROFILE"
    echo "Available profiles:"
    aws configure list-profiles
    exit 0
fi

# Export the profile name
export AWS_PROFILE=$profile

# Extract and export the credentials manually
export AWS_ACCESS_KEY_ID=$(aws configure get aws_access_key_id --profile $profile)
export AWS_SECRET_ACCESS_KEY=$(aws configure get aws_secret_access_key --profile $profile)
export AWS_DEFAULT_REGION=$(aws configure get region --profile $profile)

# Optional: get session token if it exists
SESSION_TOKEN=$(aws configure get aws_session_token --profile $profile)
if [ ! -z "$SESSION_TOKEN" ]; then
    export AWS_SESSION_TOKEN=$SESSION_TOKEN
fi

# Verify the switch
echo "Switched to profile: $profile"
aws sts get-caller-identity || { echo "Failed to verify credentials. Please check your AWS configuration."; exit 1; }