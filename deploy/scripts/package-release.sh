#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUTPUT_DIR="${ROOT_DIR}/dist"
ARCHIVE_PATH="${OUTPUT_DIR}/machine-image-uploader.tar.gz"

mkdir -p "${OUTPUT_DIR}"
tar \
  --exclude='.git' \
  --exclude='dist' \
  --exclude='dashboard/node_modules' \
  -czf "${ARCHIVE_PATH}" \
  -C "${ROOT_DIR}" \
  README.md TODO.md docs deploy machine_client server worker dashboard scripts requirements-machine-client.txt requirements-server.txt requirements-worker.txt config.example.json server-config.example.json

printf 'Created %s\n' "${ARCHIVE_PATH}"
