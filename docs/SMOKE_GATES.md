# Smoke Gates

Read when: defining Phase 0 verification, CI gates, release checks, or local
handoff checks for MLJ-P0-007.

Run commands from the repository root unless a step says otherwise. Marked
network-dependent checks need external services, package registries, Docker
base images, model providers, or Hugging Face access.

## Required Phase 0 Gates

### Python Tests

Purpose: offline Python regression suite.

```bash
UV_CACHE_DIR=/tmp/ml-junior-uv-cache uv run --extra dev pytest
```

Network: no network expected after dependencies are available. First dependency
sync may hit the package index if the uv cache is empty.

### Frontend Lint

Purpose: TypeScript/React lint gate. Present in `frontend/package.json`.

```bash
cd frontend
npm run lint
```

Network: no network expected after `node_modules` is installed. Use `npm ci`
first on a clean checkout; that install step is network-dependent.

### Frontend Build

Purpose: TypeScript build plus Vite production bundle. Present in
`frontend/package.json`.

```bash
cd frontend
npm run build
```

Network: no network expected after `node_modules` is installed. Use `npm ci`
first on a clean checkout; that install step is network-dependent.

### Backend Health Smoke

Purpose: verify the FastAPI app starts and the process health route responds.

Terminal 1:

```bash
PYTHONPATH="$PWD:$PWD/backend" uv run uvicorn backend.main:app --host 127.0.0.1 --port 7860
```

Terminal 2:

```bash
curl -fsS http://127.0.0.1:7860/api/health
```

Expected shape:

```json
{"status":"ok","active_sessions":0,"max_sessions":200}
```

Network: `/api/health` itself is offline. Startup may need dependency sync on a
clean machine.

Do not use `/api/health/llm` as the default smoke gate. It makes a real LLM
provider request and needs valid provider credentials.

### Docker Build Smoke

Purpose: verify the production image can build the frontend, install Python
runtime dependencies, and package backend/static assets.

```bash
docker build -t ml-junior-smoke .
```

Network: yes. This pulls base images and installs npm/uv dependencies unless
already cached.

### Docker Start Smoke

Purpose: verify the built image starts and serves backend health.

Terminal 1:

```bash
docker run --rm -p 7860:7860 ml-junior-smoke
```

Terminal 2:

```bash
curl -fsS http://127.0.0.1:7860/api/health
```

Network: no network expected for `/api/health` after the image exists. Creating
sessions, checking `/api/health/llm`, using MCP, creating sandboxes, or running
HF Jobs is network/API-key dependent.

Note: `backend/start.sh` exits 0 after uvicorn exits non-zero, including port
conflicts. Treat the HTTP health response as the pass/fail signal, not only the
container exit code.

## Optional Network-Dependent Checks

Use these when validating provider and HF integration, not as mandatory offline
Phase 0 gates:

- `/api/health/llm`: requires model provider credentials and network.
- Creating a backend session: may call HF username resolution and MCP/OpenAPI
  setup paths.
- `sandbox_create`: requires HF token, HF API access, Space duplication, and
  sandbox health polling.
- `hf_jobs`: requires HF token, HF Jobs availability, and possibly paid
  hardware depending on flavor.
- MCP tool loading: requires configured MCP server reachability.

## Current Gate Boundary

Current behavior:

- The required gates prove repository tests, frontend static correctness,
  backend process health, and Docker packaging/startup health.
- They do not prove LLM quality, full SSE chat flow, sandbox execution, HF Jobs,
  or quota/auth behavior.

ML Junior target behavior:

- Future gates should add authenticated session creation, SSE turn streaming,
  approval flow, compaction, and sandbox/job checks once they are stable enough
  to run deterministically in CI or an explicitly network-enabled smoke suite.
