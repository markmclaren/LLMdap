# LLMDAP Specification — v0.1 (draft)

LLMDAP lets an application ask for a model by **logical service name** (for
example `coding-large`) and get back everything it needs to call that model
directly: endpoint, wire format, model ID, how to find the credential, and
what data the endpoint is cleared to receive. It is a lookup, not a proxy;
inference traffic never passes through LLMDAP.

The key words MUST, SHOULD and MAY are used as in RFC 2119.

## 1. Directory document

A directory is a JSON object:

```json
{
  "llmdap_version": "0.1",
  "records": {
    "<service name>": { ...record... }
  }
}
```

It may be a local file or served over HTTPS (conventionally at
`https://<domain>/.well-known/llmdap.json`, as `application/json`). Remote
directories MUST use HTTPS. A JSON Schema is in
[`schema/llmdap-directory.schema.json`](schema/llmdap-directory.schema.json).

## 2. Record

| Field | Required | Meaning |
|---|---|---|
| `endpoint` | yes | Base URL of the inference API. |
| `dialect` | yes | Request format the endpoint expects: `openai-chat`, `anthropic-messages` or `ollama`. Other values MAY be used by agreement. |
| `model` | yes | Model ID to send to the endpoint. |
| `auth` | yes | How the client obtains a credential (section 4). |
| `classification` | no | Most sensitive data the endpoint may receive: `public` < `internal` < `confidential` < `restricted`. Default `public`. |

## 3. Resolution

A client is configured with an ordered list of directories (for example a
personal file, then an organisation's HTTPS directory). To resolve a name it:

1. Uses the environment variable `LLMDAP_OVERRIDE_<NAME>` if set (name
   upper-cased, `-` → `_`), whose value is a record as JSON.
2. Otherwise takes the record from the **first** directory that contains the
   name. A missing local file is skipped; any other read error MUST be reported.

## 4. Credentials (`auth`)

Records MUST NOT contain secrets. `auth.method` is one of:

* `none` — no credential.
* `env` — read it from the environment variable named in `locator`.
* `portal-request` — the user has no access yet; the client MUST fail with a
  message pointing to the onboarding URL in `locator`.

The credential is sent in header `auth.header` (default `Authorization`) with
prefix `auth.prefix` (default `Bearer `). Clients MAY support further methods
through pluggable handlers (see section 6).

## 5. Classification check

If the caller supplies a required classification, the client MUST refuse a
record whose `classification` is lower, and MUST do so **before** fetching any
credential or contacting the endpoint. An unknown classification value MUST be
treated as lower than all others.

## 6. Possible extensions

Not part of v0.1, and not implemented by the reference client:

* **More credential methods**, such as OAuth 2.0 token exchange (RFC 8693)
  against an organisation's identity provider, or fetching from a secret store
  (`vault://…`). The reference client's `register_auth_handler()` is the hook.
* **Other directory backends**: DNS (`SRV`/`TXT` records) or an existing LDAP /
  Active Directory tree.
* **More record metadata**: cache lifetime, data-retention guarantees, region,
  and capability hints (context window, tool use, vision).
