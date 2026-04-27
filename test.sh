#!/usr/bin/env bash
set -euo pipefail
source .env
cd "$(dirname "$0")"

# Rebuild Go binary
(cd go && GOTOOLCHAIN=local go build -o ../drift-fixer-go ./cmd/drift-fixer/)

# # Reset test fixture
# git checkout examples/main.tf

# Run
./drift-fixer-go -path examples/ -verbose "$@"

# uv run drift-fixer --path examples/ --verbose