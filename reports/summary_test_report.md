# Test summary

**FAILED** — 46 passed, 1 failed, 1 skipped.

## What was checked
- Frontend login/demo controls, staff action wiring, chat refresh and voice integration; Vite build/browser smoke where available.
- Backend SQLite read-only protection, parameterized SQL, cross-customer isolation, injection screening, RBAC/session controls and refund idempotency.

## Findings
- Failed: Realtime WebRTC uses the official SDK multipart encoder
- Skipped: Browser smoke test — Python Playwright is not installed

Live API-provider/voice calls and real deployment/load testing are outside this local automated run. The current environment could not install npm dependencies and does not have the OpenAI/Chroma packages needed for full API startup.
