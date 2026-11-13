# LLMDAP Specification — Version 0.1 (Draft)

* **Title:** Lightweight Language Model Directory Access Protocol (LLMDAP)
* **Version:** 0.1-draft
* **Status:** Experimental / Request for Comments

---

## 1. Abstract

The Lightweight Language Model Directory Access Protocol (LLMDAP) defines a standardized control-plane mechanism for discovering Large Language Model (LLM) inference endpoints, wire dialects, governance constraints, and credential brokers without placing a proxy in the inference data path.

## 2. Terminology

The key words **"MUST"**, **"MUST NOT"**, **"REQUIRED"**, **"SHALL"**, **"SHOULD"**, and **"MAY"** in this document are to be interpreted as described in RFC 2119.

* **Logical Service Name:** A human-readable capability identifier requested by a client (e.g., `coding-large`, `fast-embed`, `general-reasoning`).
* **Directory Record:** A structured metadata object describing how to connect to, authenticate with, and govern a specific inference backend.
* **Dialect:** The wire protocol and payload format expected by the target inference endpoint (e.g., `openai-chat`, `anthropic-messages`).
* **Auth Broker:** A mechanism referenced by a Directory Record that resolves runtime credentials without embedding raw secrets in the directory.

## 3. Resolution Hierarchy & Search Path

An LLMDAP client **MUST** support ordered resolution across a chain of directory sources (analogous to `/etc/nsswitch.conf` or DNS search domains).

1. **Process / Environment Overrides:** Explicit runtime overrides (`LLMDAP_OVERRIDE_<NAME>`).
2. **User / Local Directory:** Local filesystem path (default: `~/.config/llmdap/directory.json` on POSIX, `%APPDATA%\llmdap\directory.json` on Windows).
3. **Organizational / Network Directory:** HTTPS `.well-known` endpoint (`https://<domain>/.well-known/llmdap.json`), DNS-SD (`_<name>._llmdap._tcp.<domain>`), or LDAP tree (`ou=llmdap,...`).

Resolution **MUST** stop at the first matching record unless a governance policy check fails and fallback is explicitly enabled by the caller. Clients **MUST** respect the record's `ttl` (Time-To-Live in seconds) when caching resolved records.

## 4. Directory Record Format

A canonical LLMDAP Directory Record **MUST** contain the following fields:

| Field | Type | Requirement | Description |
| :--- | :--- | :--- | :--- |
| `endpoint` | URI String | **REQUIRED** | Base URL of the inference API (e.g., `https://api.anthropic.com/v1`). |
| `dialect` | String | **REQUIRED** | Wire protocol identifier (`openai-chat`, `openai-responses`, `anthropic-messages`, `ollama`, `google-genai`, `bedrock-converse`). |
| `model` | String | **REQUIRED** | Target model string passed to the inference API. |
| `auth` | Object | **REQUIRED** | Credential resolution descriptor (see Section 5). |
| `ttl` | Integer | **OPTIONAL** | Cache lifetime in seconds. Defaults to `3600`. |
| `governance` | Object | **OPTIONAL** | Data classification, retention, and residency metadata (see Section 6). |
| `capabilities` | Object | **OPTIONAL** | Advisory feature flags (`context_window`, `supports_tools`, `supports_vision`, `supports_structured_outputs`). |

## 5. Authentication Brokering (`auth`)

Directory Records **MUST NOT** contain raw static secrets (such as API keys or bearer tokens). Instead, the `auth` object defines a `method` and an optional `locator`:

* **`none`**: No authentication header required (e.g., loopback or air-gapped local inference).
* **`env`**: Read credential from the local environment variable named in `locator`.
* **`oidc-exchange`**: Perform an OAuth 2.0 Token Exchange (RFC 8693) or client-credentials grant against `issuer` for target `audience` to obtain a short-lived bearer token.
* **`secret-store`**: Fetch secret dynamically from a pluggable secret manager URI specified in `locator` (e.g., `vault://...`, `azure-kv://...`, `aws-sm://...`).
* **`portal-request`**: Indicates the user lacks provisioned access. The client **MUST** raise an actionable error directing the user to the onboarding URL in `locator`.

Optional `header` (default: `Authorization`) and `prefix` (default: `Bearer `) fields control how the resolved token is injected into HTTP requests.

## 6. Governance Enforcement (`governance`)

To prevent accidental data leakage across trust boundaries, records **MAY** declare:

* `data_classification`: Ordered sensitivity tier (`public` < `internal` < `confidential` < `restricted`).
* `zero_data_retention`: Boolean indicating whether the upstream endpoint contractually guarantees zero prompt/response retention.
* `region`: Jurisdictional boundary identifier (e.g., `uk`, `eu-west`, `on-prem`).

If a client specifies a `required_classification` during lookup, the client **MUST** verify that the resolved record's `data_classification` is equal to or higher than the requested tier **before** resolving credentials or returning the endpoint.

## 7. Transport Bindings

### 7.1 HTTPS `.well-known` Binding

Directories served over HTTPS **MUST** use `Content-Type: application/json` and serve a root object containing `"llmdap_version": "0.1"` and a `"records"` map keyed by Logical Service Name.

### 7.2 DNS-SD Binding (`SRV` + `TXT`)

A logical service `<name>` under `<domain>` is queried at `_<name>._llmdap._tcp.<domain>`:

* **SRV Record:** Defines target host, port, priority, and weight.
* **TXT Record:** Contains `key=value` pairs for `path`, `tls` (`true`|`false`), `dialect`, `model`, `auth`, and `class`.

### 7.3 LDAP Binding

Entries use `objectClass: llmdapService` with `cn` set to the Logical Service Name and attributes `llmdapEndpoint`, `llmdapDialect`, `llmdapModel`, `llmdapAuthMethod`, `llmdapAuthLocator`, `llmdapClassification`, `llmdapZeroDataRetention`, and `llmdapTTL`.

## 8. Security Considerations

1. **Transport Security:** Remote HTTP directory lookups **MUST** enforce TLS (`https://`).
2. **SSRF & Redirect Protection:** Clients resolving untrusted or third-party directories **SHOULD** validate resolved `endpoint` hosts against an allowlist to prevent Server-Side Request Forgery (SSRF) into internal network endpoints.
3. **Token Scoping:** Short-lived tokens minted via `oidc-exchange` **SHOULD** be audience-restricted (`aud`) to the specific inference host or broker.

