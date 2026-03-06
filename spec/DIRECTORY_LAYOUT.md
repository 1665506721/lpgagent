LPG-AgentOps Directory Layout (Frozen)

This document defines the frozen directory layout of the project.
Any changes to items in Frozen Zones require a Change Proposal and explicit approval.

1. Root Layout (Frozen)
.
├── backend/
│   ├── config/                 # Django project settings & urls
│   ├── core/                   # Core models: UserProfile, Order, Ticket, MaintenanceRequest
│   ├── agent/                  # LangChain orchestrator, contract schemas, policy engine, memory
│   ├── knowledge_base/         # RAG docs and vector store utilities
│   ├── spec/                   # OPTIONAL: backend-specific specs if needed
│   ├── manage.py
│   └── requirements.txt
├── frontend/
│   ├── src/
│   ├── public/
│   ├── index.html
│   ├── vite.config.ts
│   ├── package.json
│   └── README.md
├── spec/
│   ├── DIRECTORY_LAYOUT.md     # This file (Frozen)
│   ├── API_CONTRACT.md         # API contract (Frozen)
│   └── DB_SCHEMA.md            # Database schema (Frozen)
├── docker-compose.yml          # Frozen services & env names
├── README.md
└── .env.example

2. Frozen Zones

The following items are Frozen and must not be changed without explicit approval:

A) Directory Structure

backend/

frontend/

spec/

docker-compose.yml

B) Backend Submodules (must exist)

backend/core/

backend/agent/

backend/knowledge_base/

C) Key Entry Points (must exist)

backend/manage.py

backend/config/settings.py (or equivalent in backend/config/)

backend/config/urls.py

frontend/src/main.tsx

frontend/src/App.tsx

3. Allowed Extensions (Non-frozen)

The following modifications are allowed without approval:

Adding new files inside existing directories:

e.g., backend/agent/tools/*.py

e.g., frontend/src/components/*.tsx

Adding tests:

backend/tests/

frontend/src/__tests__/

4. Change Proposal Template (Required for Frozen Changes)

If any Frozen item must change, you MUST provide a proposal first:

Change Proposal

What will change: (directory/file names)

Why it must change: (justification)

Impact: (breaking changes, migration needed?)

Migration steps: (exact steps)

Rollback plan: (how to revert)

Wait for explicit approval before implementing.

5. Constraints for Code Generator (Codex)
Strict Requirements

Do not delete or rename directories in Frozen Zones.

Do not move modules between directories.

Do not change service names in docker-compose.yml.

Do not alter .env keys without approval.

Output Format

Every response MUST include:

Change Summary

Files Touched

Patch-only changes

Verification commands

6. Notes

This directory layout is optimized for:

Django + DRF backend

LangChain agent orchestration

RAG knowledge base with Chroma

React frontend with run trace viewer

Docker compose reproducibility