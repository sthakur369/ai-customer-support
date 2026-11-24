# Customer Support Platform

A demo support platform with ML classification, security screening, policy RAG, customer-scoped tools, staff case management.

## Install and run

Requirements: Python 3.11+, Node.js 20+ and npm.

```bash
python -m venv myenv
.\myenv\scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Add your OpenAI API key to .env
```

Start two terminals:

```bash
uvicorn api:app --host 127.0.0.1 --port 8000 --reload
```

```bash
cd frontend && npm install && npm run dev
```

Open **http://127.0.0.1:5173**.

## Demo logins and UI

| Role | ID |
|---|---:|
| Customer | `1` |
| Admin | `900001` |
| Supervisor | `900002` |

The login screen includes one-click demo ID buttons. As a customer, open **Contact customer care** and select an order, or create a general support request if no recent orders are available. Then use chat or the microphone button. Sign in as Admin or Supervisor in another browser window to review the case and reply. The customer chat refreshes staff replies automatically.

These ID-only logins are for demonstration only.

## How it works

`Chat or voice → ML intent/priority/risk → security and intervention checks → policy RAG when needed → allowlisted customer tools when needed → grounded response or human review`.

- **ML:** intent, priority and escalation-risk predictions. The bundled configuration uses the included TF-IDF/classifier artifacts.
- **Security:** hashed, expiring and revocable bearer sessions; input validation; role-based staff authorization; read-only, parameterized customer-data queries.
- **RAG:** versioned support documents with vector retrieval and reranking. Policy claims must be supported by retrieved evidence.
- **Tools:** verified order, payment and shipment lookups, refund eligibility and idempotent refund-request records. The application never transfers money or executes a payment refund.
- **Voice:** OpenAI Realtime over browser WebRTC. The browser receives a short-lived client secret, never the standard API key. Voice turns re-enter the same server-side ML/security/RAG/tool workflow.
- **Staff roles:** Admins can close cases and request/clear human review flags. The intervention control marks a case for staff attention; clearing it removes that active flag after review. Supervisors can also triage status, priority, category and assigned team.

## Automated tests

Run all three scripts through the single runner:

```bash
python run_all_tests.py
```

The runner executes `tests/test_frontend.py` and `tests/test_backend.py`, then writes:

- `reports/summary_test_report.md` — quick outcome.
- `reports/detailed_test_report.md` — individual checks and captured output.

Run either test script separately with `python tests/test_frontend.py` or `python tests/test_backend.py`. Install frontend dependencies first for the Vite build and browser smoke test. Skipped checks are clearly reported.

## Configuration and limitations

- Use `ML_MODEL=traditional_ml` or `ML_MODEL=huggingface` u
