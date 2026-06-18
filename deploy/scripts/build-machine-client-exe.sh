#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV_PYTHON="${ROOT_DIR}/.venv/bin/python"

if [ ! -x "${VENV_PYTHON}" ]; then
  printf 'Missing virtualenv python at %s\n' "${VENV_PYTHON}" >&2
  exit 1
fi

"${VENV_PYTHON}" -m pip install -r "${ROOT_DIR}/requirements-packaging.txt"
"${VENV_PYTHON}" -m PyInstaller --noconfirm --clean "${ROOT_DIR}/packaging/pyinstaller/machine_client.spec"

printf 'Machine client executable output: %s\n' "${ROOT_DIR}/dist/uploadtool-client"
