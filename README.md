# AskforWrite AI Company OS

Recovery-first implementation of the AskforWrite Company OS MVP. The current
workflow covers offline Discovery, evidence-only Research, Manager coordination,
owner approvals, Sales requirement capture, and an approved Field Force task
capability.

The bundled organizations use reserved `.example.com` domains and are synthetic
test fixtures. They are not real prospects. Discovery does not contact anyone
or claim that an external capability ran. Research only synthesizes supplied
evidence. External outreach is never sent. Proposal delivery requires a separate
owner approval, and the Field Force adapter reports success only after task
status readback. PostgreSQL is the deployment target; the default local
development URL uses SQLite. No live PostgreSQL or production Field Force
deployment has been verified in this environment.

## Run the offline checks

```powershell
python -m unittest discover -s tests -v
```

## Run the API

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
Copy-Item .env.example .env
# Configure PostgreSQL and unique random manager, owner, and Field Force tokens in .env.
docker compose up -d postgres
python -m alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Set `FIELD_FORCE_BASE_URL` to the Unolo API base URL and `FIELD_FORCE_SERVICE_TOKEN`
to the same secret configured as `COMPANY_OS_SERVICE_TOKEN` in the Unolo service.
Use distinct 32+ character API keys for `MANAGER_API_KEY` and `OWNER_API_KEY`.

## MVP Endpoints

- `POST /v1/manager/execute` runs deterministic Discovery, source-grounded Research, and queues owner approvals.
- `POST /v1/approvals` requests an approval; only the owner key can list approvals or submit decisions.
- `POST /v1/sales/execute` captures manually recorded notes for an owner-approved and researched lead, then drafts a proposal.
- `POST /v1/approvals/{approval_id}/decision` records the owner’s decision. It does not send outreach or a proposal.
- `POST /v1/delivery/execute` sends an approved proposal’s task to Field Force, using `assigned_to`, optional `due_date`, and an idempotency key.
- `GET /v1/delivery/status/{task_id}` returns gateway status and verified receiver evidence.

All endpoints require `X-API-Key`. Send `X-Correlation-ID` to trace a request.
The gateway and Field Force service both require idempotency keys for mutations.
The Unolo task operation requires the assignee to exist and be active.

Open `http://localhost:8000/docs` for the API. Every data route requires an
`X-API-Key` in all environments. Use a manager key for capability calls and an
owner key to list or decide approvals. Approval decisions only record permission;
they never perform outreach. Store real keys outside source control and rotate
them. Audit rows are append-only through the application ORM, while production
database roles or triggers must enforce that boundary against direct SQL access.

## Tests

```powershell
python -W error::DeprecationWarning -m unittest discover -s tests -v
python -m alembic check
```

The Field Force service has a separate Node contract suite in its project
directory: `npm test -- tests/companyOsApi.test.js`.