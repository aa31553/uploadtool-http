#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKUP_DIR="${ROOT_DIR}/backups"
STAMP="$(date +%Y%m%dT%H%M%S)"
TARGET="${BACKUP_DIR}/runtime-backup-${STAMP}.tar.gz"

mkdir -p "${BACKUP_DIR}"

tar -czf "${TARGET}" \
  -C "${ROOT_DIR}" \
  config.json server-config.json runtime 2>/dev/null || true

printf 'Created backup %s\n' "${TARGET}"
