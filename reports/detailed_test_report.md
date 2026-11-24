# Automated test report

- Started: 2026-11-24T12:59:03+05:30
- Finished: 2026-11-24T12:59:12+05:30
- Overall: **FAILED**
- Results: **46 passed · 1 failed · 1 skipped**

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
- PASS: voice uses browser WebRTC
- PASS: voice uses authenticated server endpoints
- PASS: voice SDP is sent to the authenticated backend, not directly to OpenAI
- PASS: voice handles completed Realtime function calls
- PASS: browser bundle does not contain a standard OpenAI API key
- PASS: voice controls have styling
- PASS: Vite production build — > support-portal@1.0.0 build | > vite build |  | [36mvite v6.4.6 [32mbuilding for production...[36m[39m | transforming... | [32mâœ“[39m 1577 modules transformed. | rendering chunks... | computing gzip size... | [2mdist/[22m[32mindex.html                 [39m[1m[2m  0.83 kB[22m[1m[22m[2m â”‚ gzip:  0.45 kB[22m | [2mdist/[22m[35massets/index-H-s1oGMI.css  [39m[1m[2m 27.96 kB[22m[1m[22m[2m â”‚ gzip:  6.62 kB[22m | [2mdist/[22m[36massets/index-ybasLQDd.js   [39m[1m[2m197.11 kB[22m[1m[22m[2m â”‚ gzip: 60.62 kB[22m | [32mâœ“ built in 6.89s[39m
- SKIP: Browser smoke test — Python Playwright is not installed
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
- FAIL: Realtime WebRTC uses the official SDK multipart encoder

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
PASS: voice uses browser WebRTC
PASS: voice uses authenticated server endpoints
PASS: voice SDP is sent to the authenticated backend, not directly to OpenAI
PASS: voice handles completed Realtime function calls
PASS: browser bundle does not contain a standard OpenAI API key
PASS: voice controls have styling
PASS: Vite production build — > support-portal@1.0.0 build | > vite build |  | [36mvite v6.4.6 [32mbuilding for production...[36m[39m | transforming... | [32mâœ“[39m 1577 modules transformed. | rendering chunks... | computing gzip size... | [2mdist/[22m[32mindex.html                 [39m[1m[2m  0.83 kB[22m[1m[22m[2m â”‚ gzip:  0.45 kB[22m | [2mdist/[22m[35massets/index-H-s1oGMI.css  [39m[1m[2m 27.96 kB[22m[1m[22m[2m â”‚ gzip:  6.62 kB[22m | [2mdist/[22m[36massets/index-ybasLQDd.js   [39m[1m[2m197.11 kB[22m[1m[22m[2m â”‚ gzip: 60.62 kB[22m | [32mâœ“ built in 6.89s[39m
SKIP: Browser smoke test — Python Playwright is not installed
```
## Backend, database and security

Exit code: `1`

```text
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
FAIL: Realtime WebRTC uses the official SDK multipart encoder
```

## Scope and limitations

- Frontend checks cover source wiring, production build when dependencies are installed, and browser smoke checks when a Playwright browser is available.
- Backend checks cover database read-only enforcement, parameterized query behavior, customer ownership, local injection screening, staff/session control implementation, and refund idempotency on a temporary database copy.
- Live OpenAI calls and live Realtime audio are not exercised. The local environment also lacks the OpenAI/Chroma runtime packages needed to start the full API lifespan.
- The npm dependency installation timed out in this environment, so the Vite production build and browser smoke test were skipped; run `cd frontend && npm ci` and rerun the test runner.
- Deployment infrastructure and multi-process/race/load behavior are not exercised by this offline test run.
