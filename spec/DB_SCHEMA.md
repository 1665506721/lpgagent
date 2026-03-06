LPG-AgentOps API Contract (Frozen)

This document defines the frozen HTTP API contract between the frontend and backend, and between the agent orchestrator and tools.

Any breaking change requires an explicit Change Proposal + approval.

1) Base URL

Default development backend:

http://localhost:8000

All API paths are under:

/api/

2) Authentication (MVP)

MVP mode:

user_id is optional in request body.

If provided, backend resolves the user profile and enables restricted tools.

If not provided, restricted tools must be blocked by policy engine.

Future (non-MVP):

JWT or session auth can be added (requires proposal).

3) Core Endpoints (Frozen)
3.1 POST /api/chat (Frozen)

Purpose: Main agent entrypoint.
Receives user message, runs orchestrator, returns final response + run trace preview.

Request Body
{
  "message": "string (required)",
  "user_id": "int | null (optional)",
  "model_provider": "OPENAI | ANTHROPIC | LOCAL (optional, overrides env)",
  "debug": "boolean (optional, default false)"
}

Response Body
{
  "run_id": "uuid",
  "final_response": "string",
  "state": "DONE | ERROR",
  "intent": "CREATE_ORDER | MODIFY_ORDER | QUERY_ORDER | CREATE_TICKET | QUERY_TICKET | SAFETY_GUIDE | UNKNOWN",
  "risk_level": "LOW | MEDIUM | HIGH",
  "need_human": true,
  "events_preview": [
    {
      "step_index": 1,
      "state": "INIT | PLANNING | VALIDATE | EXEC_TOOL | RESPOND | DONE | ERROR",
      "tool_name": "string | null",
      "policy_result": { "allow": true, "reasons": [] },
      "created_at": "ISO-8601"
    }
  ]
}

Error Response (Frozen)
{
  "run_id": "uuid | null",
  "error": "string",
  "state": "ERROR",
  "events_preview": []
}

3.2 GET /api/runs/{run_id} (Frozen)

Purpose: Replay trace for a single agent run.
Used by frontend trace viewer.

Response Body
{
  "run_id": "uuid",
  "created_at": "ISO-8601",
  "model_provider": "OPENAI | ANTHROPIC | LOCAL",
  "events": [
    {
      "id": "int",
      "step_index": 1,
      "state": "INIT | PLANNING | VALIDATE | EXEC_TOOL | RESPOND | DONE | ERROR",
      "input_json": {},
      "output_json": {},
      "tool_name": "string | null",
      "tool_input": {},
      "tool_output": {},
      "policy_result": { "allow": true, "reasons": [] },
      "created_at": "ISO-8601"
    }
  ]
}

4) Tool Endpoints (Frozen)

NOTE: In the implementation, tools may be invoked internally by Python functions.
These endpoints must still exist for debugging and integration tests.

4.1 POST /api/tools/create_order (Frozen)
Request
{
  "user_id": "int",
  "product_type": "string",
  "quantity": 1,
  "address": "string"
}

Response
{
  "order_id": "int",
  "status": "CREATED",
  "message": "string"
}

4.2 POST /api/tools/query_order (Frozen)
Request
{
  "order_id": "int"
}

Response
{
  "order_id": "int",
  "status": "string",
  "product_type": "string",
  "quantity": 1,
  "address": "string",
  "created_at": "ISO-8601"
}

4.3 POST /api/tools/modify_order_address (Frozen)
Request
{
  "order_id": "int",
  "new_address": "string"
}

Response
{
  "order_id": "int",
  "old_address": "string",
  "new_address": "string",
  "status": "string",
  "message": "string"
}

4.4 POST /api/tools/create_ticket (Frozen)
Request
{
  "user_id": "int",
  "order_id": "int | null",
  "category": "DELIVERY_DELAY | SERVICE_ISSUE | GAS_LEAK | REFUND | OTHER",
  "description": "string"
}

Response
{
  "ticket_id": "int",
  "status": "OPEN",
  "message": "string"
}

4.5 POST /api/tools/query_ticket (Frozen)
Request
{
  "ticket_id": "int"
}

Response
{
  "ticket_id": "int",
  "status": "OPEN | IN_PROGRESS | RESOLVED | CLOSED",
  "category": "string",
  "description": "string",
  "created_at": "ISO-8601"
}

4.6 POST /api/tools/create_maintenance_request (Frozen)
Request
{
  "user_id": "int",
  "issue": "string"
}

Response
{
  "maintenance_id": "int",
  "status": "OPEN",
  "message": "string"
}

4.7 POST /api/tools/safety_search (Frozen)
Request
{
  "query": "string",
  "top_k": 4
}

Response
{
  "query": "string",
  "results": [
    {
      "doc_id": "string",
      "title": "string",
      "bullets": ["string"],
      "score": 0.123
    }
  ]
}

5) Compatibility Rules (Frozen)

Response fields must not be removed or renamed.

New fields may be added only if optional, with backward compatibility.

All timestamps must be ISO-8601 strings.

tool endpoints must remain stable even if tools are called internally.

6) Change Proposal Requirement

Any change to:

endpoint path

required fields

response field semantics
requires a Change Proposal + approval.