# Free-tier working example

A runnable LLMDAP setup using only free services. The application asks for a
logical service (`chat-github`, `chat-local`, …) and the directory decides the
endpoint, dialect, model and how to find the credential. No proxy sits in the
data path: `demo.py` calls the provider directly after resolving.

| Record | Backend | Cost | Credential (`auth.method: env`) | Cleared for |
|---|---|---|---|---|
| `chat-local` | Ollama on your machine | free, offline | none | `restricted` |
| `chat-github` | GitHub Models | free with any GitHub account | `GITHUB_TOKEN` (PAT with `models:read`, or the Actions token) | `public` |
| `chat-gemini` | Google AI Studio (OpenAI-compatible endpoint) | free tier | `GEMINI_API_KEY` from aistudio.google.com/apikey | `public` |
| `chat-groq` | Groq | free tier | `GROQ_API_KEY` from console.groq.com | `public` |
| `reasoning-premium` | Anthropic | paid | `portal-request` → tells you where to get access | `internal` |

The cloud free tiers are marked `public` with `zero_data_retention: false`
because free-tier prompts may be retained or used for product improvement.

## Run it

No install needed (stdlib only; the script imports the client from `clients/python/src`).

```bash
# Option A: fully local
ollama pull llama3.2:3b && ollama serve

# Option B: any one free key
export GITHUB_TOKEN=github_pat_...      # or GEMINI_API_KEY / GROQ_API_KEY

python examples/free-tier/demo.py --list               # what resolves on this machine
python examples/free-tier/demo.py "Explain LDAP in one sentence"
python examples/free-tier/demo.py -s chat-gemini "Hello"
python examples/free-tier/demo.py -c restricted "Patient notes..."   # only chat-local is allowed
```

Without `-s`, the demo walks `chat-local → chat-github → chat-gemini → chat-groq`
and uses the first one whose credential resolves and whose endpoint answers.

## Run with Docker Compose

Copy `.env.example` to `.env`, add one or more free-tier API keys, and run the
zero-install container:

```bash
cd examples/free-tier
cp .env.example .env
# Edit .env to add GITHUB_TOKEN, GEMINI_API_KEY, and/or GROQ_API_KEY

docker compose run --rm demo --list
docker compose run --rm demo "Explain LDAP in one sentence"
docker compose run --rm demo -s chat-gemini "Hello"
```

Or run a fully self-contained local Ollama runtime using the `local` profile
(defaults to Microsoft's `phi:2.7b`, ~1.6 GB; override with `OLLAMA_MODEL=smollm2:135m`
for an even smaller ~270 MB model):

```bash
docker compose --profile local run --rm demo-local
```

## Things to try

**Swap a model without touching code.** Put a personal override in
`~/.config/llmdap/directory.json` (searched first), or for one process:

```bash
LLMDAP_OVERRIDE_CHAT_GROQ='{"endpoint":"https://api.groq.com/openai/v1","dialect":"openai-chat","model":"openai/gpt-oss-120b","auth":{"method":"env","locator":"GROQ_API_KEY"}}' \
  python examples/free-tier/demo.py -s chat-groq "Hi"
```

**Resolve over HTTPS.** Point at the raw file on GitHub (or serve it from
GitHub Pages as `/.well-known/llmdap.json`):

```bash
python examples/free-tier/demo.py \
  -d https://raw.githubusercontent.com/markmclaren/LLMdap/main/examples/free-tier/directory.json "Hi"
```

**Zero-setup CI run.** `.github/workflows/llmdap-demo.yml` runs the tests,
validates this directory, resolves it over HTTPS and makes a real call to
GitHub Models using the workflow's own `GITHUB_TOKEN` (via
`permissions: models: read`), then checks that a `restricted` request is refused.
Trigger it from the Actions tab with "Run workflow".

Model IDs on free tiers change often (Groq withdrew `llama-3.1-8b-instant`
from its free tier in 2026), which is rather the point: update the record,
not the applications.
