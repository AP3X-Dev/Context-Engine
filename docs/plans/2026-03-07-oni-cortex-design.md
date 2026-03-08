# ONI Cortex — Product & Architecture Design

**Date:** 2026-03-07
**Status:** Approved
**Brand:** ONI Cortex — "Plug your agent into everything it needs to know."

---

## 1. Product Overview

ONI Cortex is a managed MCP retrieval service built on the Context-Engine codebase. Tenants sign up, get dedicated MCP endpoints authenticated by API key, upload their data (code, docs, structured data), and their AI agents connect via MCP to search, retrieve, and answer questions.

### Why MCP-First

MCP is the universal agent protocol in 2026. Every major AI IDE and agent framework (Claude Code, Cursor, Windsurf, Cline, OpenClaw, custom agents) speaks MCP natively. ONI Cortex's primary interface is MCP endpoints — no SDK integration or REST glue needed. Agents connect with a URL and an API key.

### Target Customers

| Segment | Use Case | Tier |
|---------|----------|------|
| Indie agent builders | Plug retrieval into their agents (code, business, legal) | Free / Pro |
| Dev teams (SMB) | Code-aware AI assistants for their repos | Team |
| Growing companies | Multi-repo, multi-doc knowledge for platform agents | Business |
| Enterprise platform teams | Custom retrieval for internal AI tools, SLA | Enterprise |

### Data Types Supported

| Type | Ingestion Method | Chunking Strategy |
|------|-----------------|-------------------|
| Code | Git clone, upload, VS Code sync | AST-based semantic chunks |
| Markdown/Text | Upload API, URL fetch | Paragraph/heading-based chunks |
| PDF | Upload API | Page-based with text extraction |
| JSON/YAML | Upload API | Key-path-based structured chunks |
| CSV | Upload API | Row-group chunks with schema awareness |
| API specs (OpenAPI) | Upload API | Endpoint-based chunks |

---

## 2. Pricing

| Tier | Price | Collections | Vectors | Queries/day | Target |
|------|-------|-------------|---------|-------------|--------|
| Free | $0 | 1 | 10K | 500 | Trial, indie builders |
| Pro | $49/mo | 5 | 250K | 10K | Solo devs, small agents |
| Team | $149/mo | 25 | 1M | 50K | Startups, dev teams |
| Business | $499/mo | 100 | 5M | 200K | Growing companies |
| Enterprise | $999+/mo | Unlimited | Unlimited | Unlimited | Platform teams, custom SLA |

### Revenue Add-ons
- Overage: $5 per 100K vectors, $2 per 10K queries beyond limit
- Custom embedding models: $50/mo
- LLM decoder (context_answer): $100/mo
- Dedicated instance: $500+/mo (enterprise)

### Path to $100K MRR
200 Pro ($9.8K) + 150 Team ($22.4K) + 80 Business ($39.9K) + 30 Enterprise ($30K) = $102.1K MRR

---

## 3. Architecture

### Deployment: Oracle ARM64 (Ampere A1)

```
┌─────────────────────────────────────────────────────────┐
│                    ONI Cortex Cloud                       │
│                  (Oracle ARM64 VPS)                       │
│                                                           │
│  ┌──────────┐   ┌──────────────┐   ┌──────────────────┐ │
│  │  Caddy    │──▸│  API Gateway │──▸│  Tenant Router   │ │
│  │  (TLS)   │   │  (FastAPI)   │   │  (MCP Dispatch)  │ │
│  └──────────┘   └──────────────┘   └──────────────────┘ │
│                         │                    │            │
│                    ┌────┴────┐          ┌────┴────┐      │
│                    ▼         ▼          ▼         ▼      │
│              ┌──────────┐ ┌──────┐ ┌──────┐ ┌────────┐  │
│              │ Auth +   │ │Meter │ │MCP   │ │MCP     │  │
│              │ Billing  │ │+Usage│ │Index │ │Memory  │  │
│              │ (Stripe) │ │Track │ │Server│ │Server  │  │
│              └──────────┘ └──────┘ └──┬───┘ └───┬────┘  │
│                                       │         │        │
│                              ┌────────┴─────────┴──┐     │
│                              │     Qdrant DB       │     │
│                              │  (collection/tenant)│     │
│                              └─────────────────────┘     │
│                                       │                   │
│                              ┌────────┴────────┐         │
│                              │   llama.cpp     │         │
│                              │   (optional)    │         │
│                              └─────────────────┘         │
└─────────────────────────────────────────────────────────┘
```

### Component Responsibilities

#### Caddy Reverse Proxy
- TLS termination with auto-HTTPS (Let's Encrypt)
- Rate limiting at edge
- Routes: `cortex.oni.bot/{tenant_id}/mcp` → API Gateway
- WebSocket/SSE passthrough for MCP connections

#### API Gateway (FastAPI) — NEW
The primary new component. Single process that handles:
- **Tenant auth**: Validate API key from `Authorization: Bearer {key}` header
- **MCP proxying**: Forward authenticated MCP requests to shared MCP servers with tenant context injected
- **Usage metering**: Count vectors stored + queries per tenant, report to Stripe
- **Rate limiting**: Enforce per-tier limits (queries/day, collections, vectors)
- **Tenant provisioning**: Signup, API key management, collection CRUD
- **Billing webhooks**: Stripe webhook handler for subscription lifecycle

#### Tenant Router (MCP Dispatch)
- Extracts tenant ID from authenticated request
- Injects tenant-scoped collection name: `{tenant_id}_{collection_name}`
- Forwards MCP tool calls to shared MCP indexer/memory server
- Returns responses with tenant metadata stripped

#### MCP Servers (Modified Existing)
- MCP Indexer Server: Accept `tenant_id` context parameter on all tools
- MCP Memory Server: Accept `tenant_id` context parameter
- Both run as shared processes (not per-tenant)
- Collection name dynamically set from tenant context

#### Qdrant (Existing)
- Collection-per-tenant isolation: `{tenant_id}_codebase`, `{tenant_id}_docs`, etc.
- Shared Qdrant instance for all tenants
- Tenant deletion = drop their collections
- Snapshots for backup/restore

#### Auth + Billing — NEW
- Extends existing `auth_backend.py` for multi-tenant
- PostgreSQL for tenant records (SQLite won't scale)
- Stripe integration: subscriptions, metered billing, invoices
- API key generation: `oni_live_{random}` / `oni_test_{random}`
- JWT session tokens for dashboard access

#### Upload Service (Modified Existing)
- Auth validates tenant API key before accepting uploads
- Routes to tenant-specific workspace directory: `/work/{tenant_id}/`
- Triggers indexing into tenant's collections
- Enforces tier limits (vector count, file size)

---

## 4. Multi-Tenancy Design

### Isolation Model: Collection-per-Tenant

```
Tenant "acme" → Collections:
  acme_codebase    (code repos)
  acme_docs        (documentation)
  acme_knowledge   (memories/notes)

Tenant "startup" → Collections:
  startup_codebase
  startup_api_specs
```

### Tenant Data Model (PostgreSQL)

```sql
CREATE TABLE tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    plan VARCHAR(50) NOT NULL DEFAULT 'free',
    stripe_customer_id VARCHAR(255),
    stripe_subscription_id VARCHAR(255),
    api_key_live VARCHAR(255) UNIQUE NOT NULL,
    api_key_test VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE tenant_collections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,
    collection_name VARCHAR(255) NOT NULL,
    data_type VARCHAR(50) NOT NULL DEFAULT 'code',
    vector_count INTEGER DEFAULT 0,
    config JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tenant_id, collection_name)
);

CREATE TABLE usage_records (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID REFERENCES tenants(id),
    metric VARCHAR(50) NOT NULL,  -- 'queries', 'vectors', 'uploads'
    count INTEGER NOT NULL DEFAULT 1,
    recorded_at TIMESTAMPTZ DEFAULT NOW()
);
```

### API Key Authentication on MCP

MCP clients connect with API key in the URL or header:

```json
{
  "mcpServers": {
    "oni-cortex": {
      "url": "https://cortex.oni.bot/t/{tenant_id}/sse",
      "headers": {
        "Authorization": "Bearer oni_live_abc123..."
      }
    }
  }
}
```

Alternative: API key as URL parameter for clients that don't support custom headers:
```
https://cortex.oni.bot/t/{tenant_id}/sse?key=oni_live_abc123...
```

---

## 5. Tenant Onboarding Flow

```
1. POST /api/v1/auth/signup
   Body: { email, password, name, plan: "free" }
   → Create tenant + Stripe customer
   → Generate API keys (live + test)
   → Create default collection: {tenant_id}_default
   → Return: { tenant_id, api_key_live, api_key_test, mcp_url }

2. Connect MCP client:
   URL: https://cortex.oni.bot/t/{tenant_id}/sse
   Auth: Bearer {api_key_live}

3. Upload data:
   POST /api/v1/data/upload
   Auth: Bearer {api_key_live}
   Body: multipart/form-data with files
   → Files stored in /work/{tenant_id}/
   → Auto-indexed into tenant's collections

4. Agent queries via MCP:
   MCP tool calls (repo_search, context_answer, etc.)
   → Routed to tenant's collections
   → Usage metered
   → Results returned via MCP protocol
```

---

## 6. Customization System

### Config-Driven (v1 — launch)

Per-tenant configuration stored in `tenant_collections.config` JSONB:

```json
{
  "chunking": {
    "strategy": "semantic",
    "max_chunk_tokens": 512,
    "overlap_tokens": 64
  },
  "search": {
    "dense_weight": 1.0,
    "lexical_weight": 0.25,
    "rrf_k": 60,
    "boosts": {
      "symbol_match": 0.25,
      "recency": 0.1,
      "core_file": 0.1
    }
  },
  "filters": {
    "default_language": null,
    "exclude_patterns": ["*.test.*", "vendor/*"],
    "include_patterns": null
  },
  "decoder": {
    "enabled": false,
    "max_tokens": 2000
  }
}
```

Tenants update config via:
- Dashboard UI
- `set_session_defaults` MCP tool (per-session overrides)
- REST API: `PUT /api/v1/collections/{id}/config`

### Plugin System (v2 — post-launch)

- Webhook hooks: pre-ingest, post-search, custom-rank
- Small Python/JS snippets uploaded as plugins
- Sandboxed execution (WASM or container)
- Marketplace for community plugins

---

## 7. ARM64 Deployment Plan

### Docker Compose (Production)

All services run on single Oracle ARM64 VPS:

| Service | Image | ARM64 Status |
|---------|-------|-------------|
| Caddy | caddy:2-alpine | Native ARM64 |
| API Gateway | Custom (FastAPI) | Python — native |
| MCP Indexer | Custom (FastMCP) | Python — native |
| MCP Memory | Custom (FastMCP) | Python — native |
| Qdrant | qdrant/qdrant | Native ARM64 |
| llama.cpp | Custom build | ARM64 build exists |
| PostgreSQL | postgres:16-alpine | Native ARM64 |
| Upload Service | Custom (FastAPI) | Python — native |

### Resource Estimates (Ampere A1, 4 OCPU / 24GB RAM)

| Service | CPU | RAM |
|---------|-----|-----|
| Qdrant | 1 OCPU | 8GB |
| MCP Indexer | 0.5 OCPU | 2GB |
| MCP Memory | 0.25 OCPU | 1GB |
| API Gateway | 0.5 OCPU | 1GB |
| PostgreSQL | 0.25 OCPU | 1GB |
| Upload Service | 0.25 OCPU | 1GB |
| Caddy | 0.1 OCPU | 256MB |
| llama.cpp | 1 OCPU | 4GB |
| Embedding model | shared | 2GB |
| **Total** | ~3.85 OCPU | ~20GB |

Fits within 4 OCPU / 24GB. Scale to larger instance as tenants grow.

---

## 8. Domain & Branding

- **Product:** ONI Cortex
- **Domain:** cortex.oni.bot (or onicortex.com)
- **API Base:** https://cortex.oni.bot
- **MCP URL pattern:** https://cortex.oni.bot/t/{tenant_id}/sse
- **Dashboard:** https://cortex.oni.bot/dashboard
- **Docs:** https://cortex.oni.bot/docs

---

## 9. Go-to-Market

### Launch Strategy
1. **Private beta** — 20 hand-picked agent builders, free Team tier for 3 months
2. **Public launch** — Product Hunt, Hacker News, MCP community channels
3. **Content marketing** — "How to add memory to your AI agent in 5 minutes"
4. **Integration partnerships** — Featured in Claude Code, Cursor, Windsurf marketplaces

### Distribution Channels
- MCP server directories/registries
- VS Code marketplace (existing extension, rebrand)
- npm registry (@oni/cortex-bridge)
- Python package (oni-cortex CLI)
- Direct outreach to AI agent builders

---

## 10. Engineering Priorities (Build Order)

### Phase 1: Multi-Tenant Core (Weeks 1-3)
1. API Gateway with tenant auth (API keys)
2. Tenant Router — MCP request dispatch with collection scoping
3. PostgreSQL tenant data model
4. Tenant onboarding API (signup → provision → return endpoints)
5. Modify MCP servers to accept tenant context

### Phase 2: Billing & Limits (Weeks 3-4)
6. Stripe integration (subscriptions, API key provisioning)
7. Usage metering middleware
8. Rate limiting per tier
9. Overage tracking and billing

### Phase 3: Data Types (Weeks 4-6)
10. Document ingestion pipeline (markdown, PDF, text)
11. Structured data ingestion (JSON, CSV, API specs)
12. Chunking strategy abstraction (configurable per collection)

### Phase 4: Dashboard & DX (Weeks 6-8)
13. Tenant dashboard (React or HTMX)
14. Collection management UI
15. Usage analytics and billing view
16. API key rotation
17. Config editor for search/chunking customization

### Phase 5: Production Hardening (Weeks 8-10)
18. ARM64 production Docker compose
19. Caddy reverse proxy with TLS
20. Backup/restore for tenant data
21. Monitoring and alerting
22. Documentation site

### Phase 6: Growth (Ongoing)
23. VS Code extension rebrand to ONI Cortex
24. npm/PyPI package for CLI access
25. Plugin system v2
26. Horizontal scaling (multiple VPS nodes)
