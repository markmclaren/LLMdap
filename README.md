# LLMDAP — Lightweight Language Model Directory Access Protocol

**Zero-proxy service discovery, dialect negotiation, and credential brokering for LLM endpoints.**

[![Status: Draft Specification](https://img.shields.io/badge/status-draft%20v0.1-blue.svg)](#specification)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## The Problem

Today, every AI application, CLI tool, and research script forces developers to hardcode or manually configure three fragile parameters:

1. **Endpoint URL** (`https://api.openai.com/v1`, `http://gpu-node:11434/v1`, etc.)
2. **Model Identifier** (`claude-sonnet-4-6`, `qwen3-coder:32b`, etc. — which deprecate constantly)
3. **Static API Keys** (scattered across `.env` files, CI secrets, and vendor portals)

When teams outgrow single-key `.env` files, the industry's default answer is a **data-plane reverse proxy** (LiteLLM, Portkey, OpenRouter). While proxies solve billing and routing, they introduce a stateful bottleneck, added latency, and a single point of failure.

## The Solution: Control-Plane Discovery (LDAP/JNDI for LLMs)

In enterprise infrastructure, applications don't hardcode database IPs or credentials—they look up a logical service name via **LDAP**, **JNDI**, or **DNS-SD** and receive the connection parameters needed to connect directly.

**LLMDAP** brings this exact pattern to AI inference:

```text
┌─────────────┐   1. Lookup "coding-large"     ┌────────────────────┐
│ Application │ ─────────────────────────────► │  LLMDAP Directory  │
│ (Python/JVM)│ ◄───────────────────────────── │ (JSON / LDAP / DNS)│
└──────┬──────┘   2. Endpoint, Dialect,        └────────────────────┘
       │             Model ID, Auth Locator
       ├────────── 3. Fetch short-lived token ─► [Vault / OIDC IdP]
       │
       └────────── 4. Direct Inference Stream ─► [vLLM / Anthropic / Bedrock]
                      (Zero proxy in data path)
```

### Key Principles

* **Zero Proxy Overhead:** LLMDAP operates strictly in the **control plane**. Once resolved, inference traffic flows directly from your client SDK to the model host.
* **No Secrets in the Directory:** Records never store raw API keys. Instead, they specify an `auth` broker (`none`, `env`, `oidc-exchange`, `secret-store`, or a `portal-request` onboarding URL).
* **Governance Before Connection:** Records carry `data_classification` and `zero_data_retention` metadata so clients enforce data-handling policies *before* opening a socket.
* **Pluggable Backends:** Serve records via static `/.well-known/llmdap.json` files over HTTPS, DNS `SRV`/`TXT` records, or existing OpenLDAP / Active Directory trees.

---

## Try It Now (Free-Tier Quickstart)

You can run a working, zero-install demo right from the repo using free-tier endpoints (local Ollama, GitHub Models, Google AI Studio, or Groq)—with Python stdlib only:

```bash
# Option A: fully local with Ollama
ollama pull llama3.2:3b && ollama serve

# Option B: any one free-tier API key
export GITHUB_TOKEN=github_pat_...      # or GEMINI_API_KEY / GROQ_API_KEY

# See which logical services resolve on your machine
python examples/free-tier/demo.py --list

# Run a prompt (automatically picks the first available free-tier backend)
python examples/free-tier/demo.py "Explain LDAP in one sentence"

# Enforce data governance: only local/restricted-cleared endpoints are allowed
python examples/free-tier/demo.py -c restricted "Sensitive prompt"
```

See [`examples/free-tier/README.md`](examples/free-tier/README.md) for all options (including resolving over HTTPS from GitHub and swapping models via `LLMDAP_OVERRIDE_*` without touching code).

---

## Quickstart Example

### 1. Define a Directory (`~/.config/llmdap/directory.json` or `/.well-known/llmdap.json`)

```json
{
  "llmdap_version": "0.1",
  "directory": "example.org",
  "records": {
    "coding-large": {
      "ttl": 1800,
      "endpoint": "http://gpu-node-04.internal:11434/v1",
      "dialect": "openai-chat",
      "model": "qwen3-coder:32b",
      "auth": {
        "method": "none"
      },
      "governance": {
        "data_classification": "restricted",
        "zero_data_retention": true
      }
    },
    "reasoning-cloud": {
      "ttl": 3600,
      "endpoint": "https://api.anthropic.com/v1",
      "dialect": "anthropic-messages",
      "model": "claude-sonnet-4-6",
      "auth": {
        "method": "oidc-exchange",
        "issuer": "https://auth.example.org/realms/main",
        "audience": "llmdap://anthropic-broker"
      },
      "governance": {
        "data_classification": "internal",
        "zero_data_retention": true
      }
    }
  }
}
```

### 2. Resolve in Application Code

```python
from llmdap import LLMDAPClient
from openai import OpenAI

# Resolves local overrides first, falling back to organizational directory
dap = LLMDAPClient([
    "file:///~/.config/llmdap/directory.json",
    "https://ai.example.org/.well-known/llmdap.json",
])

# Application asks for a capability + data policy, never a hardcoded vendor/model
target = dap.lookup("coding-large", required_classification="restricted")

# Hand off directly to the native SDK
client = OpenAI(base_url=target.endpoint, api_key=target.api_key or "unused")
response = client.chat.completions.create(
    model=target.model,
    messages=[{"role": "user", "content": "Optimize this spatial query."}],
)
```

## Repository Structure

* [`SPEC.md`](SPEC.md) — Formal LLMDAP v0.1 protocol specification (record schema, resolution order, auth brokers, DNS-SD & LDAP bindings).
* [`schema/llmdap-directory.schema.json`](schema/llmdap-directory.schema.json) — JSON Schema (Draft 2020-12) for validating directory documents.
* [`schema/llmdap.schema`](schema/llmdap.schema) — OpenLDAP `llmdapService` objectClass and attribute definitions.
* [`examples/`](examples/) — Example `.well-known/llmdap.json` directory, LDIF entries, and a runnable [`free-tier/`](examples/free-tier/README.md) demo.
* [`clients/python/`](clients/python/) — Reference zero-dependency Python resolver and CLI.

## Status & Intent

LLMDAP is published as an **open architectural idea, schema, and minimal reference implementation** for anyone to adopt, fork, or build upon—it is not an actively maintained project. Feel free to take the specification, JSON/LDAP schemas, and Python client sketch and run with them in your own tools, organizations, or standards efforts.

