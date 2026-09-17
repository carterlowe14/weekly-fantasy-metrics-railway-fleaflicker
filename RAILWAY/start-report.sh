#!/bin/bash

# Required environment variables for the report generator
REQUIRED_VARS=("PLATFORM" "LEAGUE_ID" "SEASON" "CURRENT_NFL_WEEK" "DISCORD_WEBHOOK_ID")

missing=()

for required_name in "${REQUIRED_VARS[@]}"; do
  if [ -z "${!required_name}" ]; then
    missing+=("$required_name")
  fi
done

if [ ${#missing[@]} -ne 0 ]; then
  echo "Error: The following required environment variables are missing:"
  for required_name in "${missing[@]}"; do
    echo "  - $required_name"
  done
  echo "Please set these in the Railway project settings."
  exit 1
fi

echo "All required environment variables are set. Starting report generation..."
python main.py --use-default
