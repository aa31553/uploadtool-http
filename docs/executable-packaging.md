# Executable Packaging

This project can be packaged into separate executables for the server side and machine side.

## Packaging Mode

Current packaging uses `PyInstaller` with `onedir` output.

Why `onedir` is preferred here:

- The server depends on bundled static dashboard assets and local docs assets
- The machine client depends on PyQt runtime files
- Config templates are easier to ship next to the executable

---

## Prerequisites

Create and activate the project virtual environment first:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-machine-client.txt -r requirements-server.txt -r requirements-worker.txt
```

Packaging dependency:

```bash
pip install -r requirements-packaging.txt
```

---

## Build Server Executable

```bash
bash deploy/scripts/build-server-exe.sh
```

Output directory:

```text
dist/uploadtool-server/
```

Important bundled items:

- `server/static/`
- `server-config.example.json`
- `config.example.json`

Recommended runtime files next to the executable:

- `server-config.json`
- writable `runtime/` directory

---

## Build Machine Client Executable

```bash
bash deploy/scripts/build-machine-client-exe.sh
```

Output directory:

```text
dist/uploadtool-client/
```

Important bundled items:

- `config.example.json`

Recommended runtime files next to the executable:

- `config.json`
- writable image and buffer directories referenced by config

---

## Spec Files

- Server: `packaging/pyinstaller/server.spec`
- Machine client: `packaging/pyinstaller/machine_client.spec`

---

## Notes

- The server executable still expects the same runtime configuration model as `python -m server`
- The machine executable still expects the same runtime configuration model as `python -m machine_client`
- If you package on Windows, build on Windows; if you package on Linux, build on Linux
- PyInstaller output is platform-specific and not portable across operating systems
