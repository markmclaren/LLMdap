# LLMDAP

**Look up an LLM by name instead of hard-coding its URL, model and key.**

Applications usually hard-code three things that keep changing: the endpoint
URL, the model ID (which gets deprecated), and an API key. LLMDAP moves them
into a shared directory, the way LDAP or DNS do for databases and servers:

```text
app ──"chat-github"──► directory ──► endpoint, model, dialect, where the key is
 │
 └──────────────── calls the model directly (no proxy in between)
```

Each record also says what data the endpoint is cleared for, so an app handling
sensitive data can refuse a public endpoint *before* sending anything.

## Try it (free, no install)

You need Python 3.10+ and **one** of these:

* a GitHub account: create a token at <https://github.com/settings/tokens>
  with the `models:read` permission, then `export GITHUB_TOKEN=...`
* a Google AI Studio key: `export GEMINI_API_KEY=...` (<https://aistudio.google.com/apikey>)
* [Ollama](https://ollama.com) running locally: `ollama pull llama3.2:3b`

```bash
git clone https://github.com/markmclaren/LLMdap && cd LLMdap

python examples/demo.py --list                      # what's available to you
python examples/demo.py "Explain LDAP in one sentence"
python examples/demo.py -c restricted "Patient notes..."   # only the local model qualifies
```

The demo asks the directory for each service in turn and uses the first that
works. Its directory is [`examples/directory.json`](examples/directory.json):

```json
"chat-github": {
  "endpoint": "https://models.github.ai/inference",
  "dialect": "openai-chat",
  "model": "openai/gpt-4.1-mini",
  "auth": { "method": "env", "locator": "GITHUB_TOKEN" },
  "classification": "public"
}
```

No secrets are stored: `auth` only says *where* the key comes from.

The GitHub Action in this repo runs the same demo for real on every push,
using the workflow's own token, so it needs no setup.

## Use it in your code

```python
from llmdap import LLMDAPClient
from openai import OpenAI

dap = LLMDAPClient([
    "~/.config/llmdap/directory.json",                 # personal overrides first
    "https://ai.example.org/.well-known/llmdap.json",  # then your organisation's
])
target = dap.lookup("chat-github", required_classification="public")

client = OpenAI(base_url=target.endpoint, api_key=target.api_key)
reply = client.chat.completions.create(
    model=target.model,
    messages=[{"role": "user", "content": "Hello"}],
)
```

To change model or provider, edit the directory; the code stays the same. To
change one service just for yourself or one run, set
`LLMDAP_OVERRIDE_CHAT_GITHUB='{...record JSON...}'`.

Check what a name resolves to from the command line:

```bash
PYTHONPATH=clients/python/src python -m llmdap.cli lookup chat-github -d examples/directory.json
```

## What's here

* [`SPEC.md`](SPEC.md): the format and rules (short).
* [`schema/`](schema/): JSON Schema for directory files.
* [`clients/python/`](clients/python/): reference client, ~120 lines, standard library only.
* [`examples/`](examples/): the demo and its directory.

## Status

An idea plus a minimal working implementation, published for anyone to adopt,
fork or build on. It isn't actively maintained. Ideas for going further (token
exchange, DNS/LDAP backends) are listed at the end of the spec.
