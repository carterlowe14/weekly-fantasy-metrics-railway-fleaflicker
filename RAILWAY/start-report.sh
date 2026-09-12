#!/bin/bash

# Required environment variables for the report generator
REQUIRED_VARS=("PLATFORM" "LEAGUE_ID" "SEASON" "CURRENT_NFL_WEEK" "DISCORD_WEBHOOK_ID")

missing_vars=()

for var in "${REQUIRED_VARS[@]}"; do
  if [ -z "${!var}" ]; then
    missing_vars+=("$var")
  fi
done

if [ ${#missing_vars[@]} -ne 0 ]; then
  echo "Error: The following required environment variables are missing:"
  for var in "${missing_vars[@]}"; do
    echo "  - $var"
  done
  echo "Please set these in the Railway project settings."
  exit 1
fi

echo "All required environment variables are set. Starting report generation..."
python main.py --use-default
