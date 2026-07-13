# MOT installation and environment configuration

## Install from the current fork

Use uv's isolated tool environment so MOT does not modify the user's system Python. Ask before
installing. HTTPS is the portable default:

```bash
uv tool install \
  "git+https://github.com/atripathy86/model_openness_tool.git@main#subdirectory=mot"
```

Use SSH only when the user requests it and GitHub SSH authentication is already configured:

```bash
uv tool install \
  "git+ssh://git@github.com/atripathy86/model_openness_tool.git@main#subdirectory=mot"
```

Replace `main` with a user-supplied tag or full commit SHA for a reproducible installation.
Verify the installed tool and record its active rule sources:

```bash
mot version
mot catalog
```

Upgrade an installation while retaining its original source settings:

```bash
uv tool upgrade model-openness-tool
mot version
mot catalog
```

If the user wants a different branch, tag, commit, transport, or fork, run `uv tool install`
again with the replacement source URL. Do not silently switch sources. Use `uv tool list` to
inspect installed tools and `uv tool dir --bin` to locate executables. Ask before
`uv tool update-shell` because it changes shell startup files.

If the user supplies a source checkout instead of authorizing installation, run:

```bash
uv run --project <mot-checkout>/mot mot version
uv run --project <mot-checkout>/mot mot catalog
```

Use `uv run --project <mot-checkout>/mot mot` as the command prefix for that session.

## Create a user workspace

Ask the user where MOT should store private configuration and generated artifacts. Create that
directory only after approval and run MOT from it. A typical workspace contains:

```text
<mot-workspace>/
├── .env                 # optional, private
├── .hf-cache/           # connector cache
├── .mot/                # review databases
└── reports/             # evaluation JSON and reviewed YAML
```

Do not create `.env` inside the installed skill or uv tool environment.

## Configure optional capabilities

A basic public Hugging Face evaluation needs no `.env` file. Ask the user which optional
capabilities are needed, then create or update a private `.env` without printing secrets.

Use this template, leaving unused values blank:

```dotenv
# Private or gated Hugging Face resources; public resources usually need no token
HF_TOKEN=

# Higher GitHub API limits or private repositories
GITHUB_TOKEN=

# Optional OpenAI-compatible semantic extraction
OPENAI_BASE_URL=
OPENAI_API_KEY=

# Optional externally operated MinerU service for PDF extraction
MINERU_SERVER_URL=

# Optional API bearer authentication; blank disables authentication
MOT_API_BEARER_TOKEN=
MOT_LOG_LEVEL=INFO

# Required only for the API persistence boundary and durable jobs
POSTGRES_DB=
POSTGRES_USER=
POSTGRES_PASSWORD=
POSTGRES_PORT=
DATABASE_URL=
```

## Configuration rules

- Never invent endpoint URLs, credentials, database passwords, or tokens. Ask the user to
  supply them or identify an existing private environment file.
- Use the standard `OPENAI_BASE_URL` and `OPENAI_API_KEY` names.
- Treat `OPENAI_API_KEY` as optional because some compatible endpoints do not authenticate.
- Use `HF_TOKEN` and `GITHUB_TOKEN` only through their environment-variable names; CLI
  `--token-env` options select a different variable without exposing its value.
- Use `MINERU_SERVER_URL` only when the user has an external MinerU service. Keep pypdf
  fallback enabled unless the user requests strict MinerU-only extraction.
- Do not start PostgreSQL, apply migrations, run workers, or start the API unless the user
  asks for service or durable-job operation.
- Keep `.env`, review databases, caches, and generated evaluation reports out of source
  control unless the user explicitly requests an attributable fixture.

For an installed tool, load a private environment file with the shell or an approved secret
manager before running `mot`; the MOT CLI does not automatically read `.env`. For a checkout,
uv can load it explicitly:

```bash
uv run --project <mot-checkout>/mot --env-file <private.env> mot <command>
```
