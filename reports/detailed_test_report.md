# Automated test report

- Started: 2026-11-24T18:45:30+05:30
- Finished: 2026-11-24T18:45:37+05:30
- Overall: **PASSED WITH SKIPS**
- Results: **55 passed · 0 failed · 1 skipped**

This report records checks actually executed. Skipped checks are not counted as passes.

## Check-by-check results

- PASS: all native frontend buttons have click handlers
- PASS: all native frontend buttons declare a button type
- PASS: all shared Button components perform an action or submit a form
- PASS: login screen includes customer demo ID
- PASS: login screen includes admin demo ID
- PASS: login screen includes supervisor demo ID
- PASS: staff case actions are wired
- PASS: staff reply action is wired
- PASS: filter reset is wired
- PASS: customer chat refresh is wired
- PASS: customer can create a support request without an order
- PASS: intervention action explains its effect
- PASS: browser bundle does not contain a standard OpenAI API key
- PASS: Vite production build — > support-portal@1.0.0 build | > vite build |  | [36mvite v6.4.6 [32mbuilding for production...[36m[39m | transforming... | [32mâœ“[39m 1577 modules transformed. | rendering chunks... | computing gzip size... | [2mdist/[22m[32mindex.html                 [39m[1m[2m  0.80 kB[22m[1m[22m[2m â”‚ gzip:  0.42 kB[22m | [2mdist/[22m[35massets/index-H-s1oGMI.css  [39m[1m[2m 27.96 kB[22m[1m[22m[2m â”‚ gzip:  6.62 kB[22m | [2mdist/[22m[36massets/index-CowjjjEy.js   [39m[1m[2m191.41 kB[22m[1m[22m[2m â”‚ gzip: 58.75 kB[22m | [32mâœ“ built in 5.22s[39m
- SKIP: Browser smoke test — Python Playwright is not installed
- PASS: simple greeting uses the deterministic fast-path classifier
- PASS: greeting classifier does not swallow a real support question
- PASS: verified order tracking bypasses RAG deterministically
- PASS: policy eligibility questions are not misclassified as database-only facts
- PASS: order status remains a database-only fact even when RAG is empty
- PASS: read-only database can execute SELECT
- PASS: generic query helper rejects SQL writes
- PASS: SQLite authorizer blocks direct write attempts
- PASS: bound SQL parameters treat injection payload as data
- PASS: SQLite database integrity check — ok
- PASS: customer can retrieve own order
- PASS: customer cannot retrieve another customer's order
- PASS: prompt-injection screening detects instruction override
- PASS: SQL-injection pattern screening detects destructive SQL
- PASS: normal support question is not flagged
- PASS: tool allowlist contains only supported functions
- PASS: refund idempotency hashing dependency is imported
- PASS: tool executor rejects unexpected arguments
- PASS: negated refund statement cannot trigger a refund request
- PASS: clear refund request can trigger a request workflow
- PASS: refund eligibility tool is customer-scoped
- PASS: refund request creates one record in isolated test DB
- PASS: refund request is idempotent
- PASS: refund tool blocks cross-customer ownership
- PASS: customer tickets GET route is attached to the endpoint (not its helper)
- PASS: support request can be created without an order ID
- PASS: portal tokens are random, hashed, expiring and revocable
- PASS: portal login has an IP rate limit
- PASS: customer and staff endpoints have separate dependencies
- PASS: staff role permissions enforce admin/supervisor separation
- PASS: customer conversation APIs omit staff-only message metadata
- PASS: customer portal strips technical metadata and internal resolution notes
- PASS: API sessions are hashed and revoked on logout
- PASS: API input models validate identifiers and message content
- PASS: customer follow-ups keep an under-review ticket session active
- PASS: CORS allows PATCH for case updates
- PASS: refund action has backend eligibility, ownership and idempotency controls
- PASS: LLM model payload does not contain customer ID
- PASS: example configuration contains only an API-key placeholder
- PASS: local environment file is excluded from Git
- PASS: Python requirements use real line breaks and include the Realtime SDK

## Execution output

## Frontend

Exit code: `0`

```text
PASS: all native frontend buttons have click handlers
PASS: all native frontend buttons declare a button type
PASS: all shared Button components perform an action or submit a form
PASS: login screen includes customer demo ID
PASS: login screen includes admin demo ID
PASS: login screen includes supervisor demo ID
PASS: staff case actions are wired
PASS: staff reply action is wired
PASS: filter reset is wired
PASS: customer chat refresh is wired
PASS: customer can create a support request without an order
PASS: intervention action explains its effect
PASS: browser bundle does not contain a standard OpenAI API key
PASS: Vite production build — > support-portal@1.0.0 build | > vite build |  | [36mvite v6.4.6 [32mbuilding for production...[36m[39m | transforming... | [32mâœ“[39m 1577 modules transformed. | rendering chunks... | computing gzip size... | [2mdist/[22m[32mindex.html                 [39m[1m[2m  0.80 kB[22m[1m[22m[2m â”‚ gzip:  0.42 kB[22m | [2mdist/[22m[35massets/index-H-s1oGMI.css  [39m[1m[2m 27.96 kB[22m[1m[22m[2m â”‚ gzip:  6.62 kB[22m | [2mdist/[22m[36massets/index-CowjjjEy.js   [39m[1m[2m191.41 kB[22m[1m[22m[2m â”‚ gzip: 58.75 kB[22m | [32mâœ“ built in 5.22s[39m
SKIP: Browser smoke test — Python Playwright is not installed
```
## Backend, database and security

Exit code: `0`

```text
PASS: simple greeting uses the deterministic fast-path classifier
PASS: greeting classifier does not swallow a real support question
[INFO] RAG skipped: factual customer/order question will use verified database context.
PASS: verified order tracking bypasses RAG deterministically
PASS: policy eligibility questions are not misclassified as database-only facts
PASS: order status remains a database-only fact even when RAG is empty
PASS: read-only database can execute SELECT
PASS: generic query helper rejects SQL writes
PASS: SQLite authorizer blocks direct write attempts
PASS: bound SQL parameters treat injection payload as data
PASS: SQLite database integrity check — ok
PASS: customer can retrieve own order
PASS: customer cannot retrieve another customer's order
PASS: prompt-injection screening detects instruction override
PASS: SQL-injection pattern screening detects destructive SQL
PASS: normal support question is not flagged
PASS: tool allowlist contains only supported functions
PASS: refund idempotency hashing dependency is imported
PASS: tool executor rejects unexpected arguments
PASS: negated refund statement cannot trigger a refund request
PASS: clear refund request can trigger a request workflow
PASS: refund eligibility tool is customer-scoped
PASS: refund request creates one record in isolated test DB
PASS: refund request is idempotent
PASS: refund tool blocks cross-customer ownership
PASS: customer tickets GET route is attached to the endpoint (not its helper)
PASS: support request can be created without an order ID
PASS: portal tokens are random, hashed, expiring and revocable
PASS: portal login has an IP rate limit
PASS: customer and staff endpoints have separate dependencies
PASS: staff role permissions enforce admin/supervisor separation
PASS: customer conversation APIs omit staff-only message metadata
PASS: customer portal strips technical metadata and internal resolution notes
PASS: API sessions are hashed and revoked on logout
PASS: API input models validate identifiers and message content
PASS: customer follow-ups keep an under-review ticket session active
PASS: CORS allows PATCH for case updates
PASS: refund action has backend eligibility, ownership and idempotency controls
PASS: LLM model payload does not contain customer ID
PASS: example configuration contains only an API-key placeholder
PASS: local environment file is excluded from Git
PASS: Python requirements use real line breaks and include the Realtime SDK
```

## Scope and limitations

- Frontend checks cover source wiring, production build when dependencies are installed, and browser smoke checks when a Playwright browser is available.
- Backend checks cover database read-only enforcement, parameterized query behavior, customer ownership, local injection screening, staff/session control implementation, and refund idempotency on a temporary database copy.
- Live OpenAI calls and live Realtime audio are not exercised. The local environment also lacks the OpenAI/Chroma runtime packages needed to start the full API lifespan.
- The npm dependency installation timed out in this environment, so the Vite production build and browser smoke test were skipped; run `cd frontend && npm ci` and rerun the test runner.
- Deployment infrastructure and multi-process/race/load behavior are not exercised by this offline test run.
