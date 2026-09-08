# ADR-007: M-Pesa adapter (real vs fake)

- **Status:** Accepted
- **DRI:** Hunter
- **Date:** 2026-09-08

## Context
CI, k6 load tests, and chaos/reconciliation drills must never touch real money or the real Daraja
API, but they still need to exercise the exact same code paths production uses — including failure
modes (timeouts, duplicate callbacks, out-of-order callbacks) that are hard to trigger on demand
against a live sandbox. The brief requires the environment to be Daraja **sandbox only**; production
Daraja credentials are out of scope for this capstone entirely.

## Decision
Define a single `MpesaAdapter` interface in `services/_shared`:
`initiateSTKPush`, `queryTransactionStatus`, `initiateB2C`, `verifyCallbackAuthenticity`. Two
implementations sit behind it:

- **`DarajaSandboxAdapter`** — real HTTP calls to the Safaricom Daraja **sandbox**, with OAuth2
  client-credentials token acquisition and caching. Used in `dev`/any deployed environment.
- **`FakeMpesaAdapter`** — deterministic, in-memory, no network calls. Used in unit/integration
  tests, CI, and k6 load/drill runs. It is driven by a small scripted-response protocol: a test can
  pre-program a scenario per request (`immediate_success`, `immediate_failure`, `delayed_timeout`,
  `duplicate_callback`, `out_of_order_callback`) so chaos drills can force "Daraja never answered" or
  "Daraja sent the same callback twice" **deterministically**, without depending on flaky real-network
  conditions to reproduce them.

Adapter selection is environment/config-driven (`MPESA_ADAPTER=sandbox|fake`), never a runtime
feature flag reachable from a request path — CI and load tests are hard-wired to `fake`; every
deployed environment is hard-wired to `sandbox`.

**Callback authenticity**: Daraja sandbox callbacks aren't cryptographically signed, so
authenticity is established by (a) a per-tenant unguessable secret path segment in the registered
callback URL (rotated via Secrets Manager, never logged), and (b) re-verifying any callback above a
configurable amount threshold, or any callback whose payload looks inconsistent with the stored
`CheckoutRequestID`, via `queryTransactionStatus` before final settlement — defense in depth rather
than trusting the callback body alone.

## Alternatives considered
- **HTTP cassette record/replay (VCR-style) against captured sandbox traffic** — rejected as the
  primary test double: brittle to sandbox contract drift, and can't cleanly express "force a
  duplicate callback on demand." Still acceptable as a supplementary contract test run occasionally
  against the real sandbox, not as the default test path.
- **Per-test HTTP client mocking, no shared fake** — rejected as the default: would let each
  service's tests drift into inconsistent assumptions about Daraja's behavior. One shared
  `FakeMpesaAdapter` behind a common interface keeps every service's tests exercising the same
  semantics.

## Consequences
- The `MpesaAdapter` interface is now a cross-team contract living in `services/_shared` — changing
  its shape requires coordinating across `payments`, `commission`, and anyone else consuming it.
- `FakeMpesaAdapter` must be actively kept representative of real Daraja quirks (whole-shilling
  amounts, exact callback field shapes) or its tests give false confidence — this is an ongoing
  maintenance cost, not a one-time build.
- Chaos/reconciliation drills become code (a scenario flag), not manual sandbox fiddling — which is
  what makes them repeatable evidence for [ADR-004](ADR-004-idempotency-and-money-integrity.md)'s
  required proof.

## Required proof (from brief)
ADR + tests: contract tests exercised against both adapters where feasible, and
`FakeMpesaAdapter` scenario tests for timeout, duplicate-callback, and out-of-order-callback cases.
