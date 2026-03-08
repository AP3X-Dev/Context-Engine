import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "API Reference — ONI Cortex",
  description:
    "Complete API reference for ONI Cortex: authentication, tenant management, collections, and MCP endpoints.",
  openGraph: {
    title: "API Reference — ONI Cortex",
    description:
      "Complete API reference for ONI Cortex: authentication, tenant management, collections, and MCP endpoints.",
    url: "https://cortex.oni.bot/docs",
  },
};

/* ---------------------------------------------------------------------------
 * Inline styles — matches the global dark theme without a separate CSS file
 * -------------------------------------------------------------------------*/

const colors = {
  bgPrimary: "#0a0a0a",
  bgSecondary: "#141414",
  bgTertiary: "#1a1a1a",
  textPrimary: "#fafafa",
  textSecondary: "#a1a1a1",
  accent: "#6366f1",
  accentHover: "#818cf8",
  border: "#2a2a2a",
} as const;

const mono = "var(--font-geist-mono), ui-monospace, monospace";

/* ---------------------------------------------------------------------------
 * Tiny helper components
 * -------------------------------------------------------------------------*/

function Badge({ children, variant }: { children: React.ReactNode; variant: "get" | "post" | "sse" }) {
  const bg =
    variant === "get"
      ? "#22c55e"
      : variant === "post"
        ? "#3b82f6"
        : "#f59e0b";
  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 10px",
        borderRadius: 6,
        fontSize: 12,
        fontWeight: 700,
        fontFamily: mono,
        letterSpacing: "0.04em",
        color: "#000",
        background: bg,
        textTransform: "uppercase",
        lineHeight: "20px",
      }}
    >
      {children}
    </span>
  );
}

function Code({ children }: { children: React.ReactNode }) {
  return (
    <code
      style={{
        fontFamily: mono,
        fontSize: 13,
        background: colors.bgTertiary,
        border: `1px solid ${colors.border}`,
        borderRadius: 6,
        padding: "2px 7px",
      }}
    >
      {children}
    </code>
  );
}

function CodeBlock({ children, title }: { children: string; title?: string }) {
  return (
    <div
      style={{
        background: colors.bgSecondary,
        border: `1px solid ${colors.border}`,
        borderRadius: 10,
        overflow: "hidden",
        marginTop: 12,
      }}
    >
      {title && (
        <div
          style={{
            padding: "8px 16px",
            fontSize: 12,
            fontFamily: mono,
            color: colors.textSecondary,
            borderBottom: `1px solid ${colors.border}`,
            background: colors.bgTertiary,
          }}
        >
          {title}
        </div>
      )}
      <pre
        style={{
          margin: 0,
          padding: 16,
          overflowX: "auto",
          fontSize: 13,
          lineHeight: 1.6,
          fontFamily: mono,
          color: colors.textPrimary,
        }}
      >
        {children}
      </pre>
    </div>
  );
}

function SectionHeading({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <h2
      id={id}
      style={{
        fontSize: 22,
        fontWeight: 700,
        marginTop: 56,
        marginBottom: 8,
        paddingBottom: 10,
        borderBottom: `1px solid ${colors.border}`,
        color: colors.textPrimary,
      }}
    >
      {children}
    </h2>
  );
}

function Field({ name, type, required, children }: { name: string; type: string; required?: boolean; children?: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 6 }}>
      <Code>{name}</Code>{" "}
      <span style={{ color: colors.textSecondary, fontSize: 13 }}>{type}</span>
      {required && (
        <span style={{ color: "#ef4444", fontSize: 12, marginLeft: 6 }}>required</span>
      )}
      {children && (
        <span style={{ color: colors.textSecondary, fontSize: 13, marginLeft: 8 }}>
          {children}
        </span>
      )}
    </div>
  );
}

function EndpointCard({
  method,
  path,
  description,
  auth,
  requestBody,
  responseExample,
  responseTitle,
  children,
}: {
  method: "GET" | "POST" | "SSE";
  path: string;
  description: string;
  auth: string;
  requestBody?: React.ReactNode;
  responseExample?: string;
  responseTitle?: string;
  children?: React.ReactNode;
}) {
  const variant = method === "GET" ? "get" : method === "POST" ? "post" : "sse";
  return (
    <div
      style={{
        background: colors.bgSecondary,
        border: `1px solid ${colors.border}`,
        borderRadius: 12,
        padding: 24,
        marginTop: 20,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <Badge variant={variant}>{method}</Badge>
        <span style={{ fontFamily: mono, fontSize: 15, color: colors.textPrimary, wordBreak: "break-all" }}>
          {path}
        </span>
      </div>
      <p style={{ color: colors.textSecondary, marginTop: 10, marginBottom: 0, fontSize: 14, lineHeight: 1.6 }}>
        {description}
      </p>
      <div
        style={{
          marginTop: 12,
          fontSize: 13,
          color: colors.textSecondary,
          display: "flex",
          alignItems: "center",
          gap: 6,
        }}
      >
        <span
          style={{
            display: "inline-block",
            width: 8,
            height: 8,
            borderRadius: "50%",
            background: auth === "None" ? "#22c55e" : colors.accent,
          }}
        />
        Auth: <span style={{ color: colors.textPrimary }}>{auth}</span>
      </div>

      {requestBody && (
        <div style={{ marginTop: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: colors.textSecondary, marginBottom: 8 }}>
            Request Body
          </div>
          {requestBody}
        </div>
      )}

      {children}

      {responseExample && (
        <CodeBlock title={responseTitle ?? "Response"}>{responseExample}</CodeBlock>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------------------
 * Sidebar navigation data
 * -------------------------------------------------------------------------*/

const navSections = [
  {
    title: "Overview",
    items: [
      { label: "Introduction", href: "#introduction" },
      { label: "Base URL", href: "#base-url" },
      { label: "Authentication", href: "#authentication" },
      { label: "Plan Tiers", href: "#plan-tiers" },
    ],
  },
  {
    title: "Endpoints",
    items: [
      { label: "POST /auth/signup", href: "#signup" },
      { label: "GET /me", href: "#me" },
      { label: "POST /me/rotate-key", href: "#rotate-key" },
      { label: "GET /collections", href: "#list-collections" },
      { label: "POST /collections", href: "#create-collection" },
      { label: "GET /health", href: "#health" },
    ],
  },
  {
    title: "MCP Transport",
    items: [
      { label: "SSE Transport", href: "#mcp-sse" },
      { label: "HTTP Transport", href: "#mcp-http" },
    ],
  },
];

/* ---------------------------------------------------------------------------
 * Page component
 * -------------------------------------------------------------------------*/

export default function CortexDocsPage() {
  return (
    <div style={{ display: "flex", minHeight: "100vh", background: colors.bgPrimary }}>
      {/* ---- Sidebar ---- */}
      <nav
        style={{
          position: "sticky",
          top: 0,
          height: "100vh",
          width: 260,
          minWidth: 260,
          overflowY: "auto",
          borderRight: `1px solid ${colors.border}`,
          padding: "32px 20px",
          background: colors.bgSecondary,
          display: "flex",
          flexDirection: "column",
          gap: 28,
        }}
      >
        <a
          href="/cortex"
          style={{
            fontWeight: 800,
            fontSize: 15,
            letterSpacing: "-0.02em",
            color: colors.textPrimary,
            textDecoration: "none",
          }}
        >
          ONI Cortex
        </a>

        {navSections.map((section) => (
          <div key={section.title}>
            <div
              style={{
                fontSize: 11,
                fontWeight: 700,
                textTransform: "uppercase",
                letterSpacing: "0.08em",
                color: colors.textSecondary,
                marginBottom: 10,
              }}
            >
              {section.title}
            </div>
            <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 4 }}>
              {section.items.map((item) => (
                <li key={item.href}>
                  <a
                    href={item.href}
                    style={{
                      color: colors.textSecondary,
                      textDecoration: "none",
                      fontSize: 13,
                      lineHeight: "28px",
                      display: "block",
                      padding: "0 8px",
                      borderRadius: 6,
                    }}
                  >
                    {item.label}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      {/* ---- Main content ---- */}
      <main
        style={{
          flex: 1,
          maxWidth: 820,
          margin: "0 auto",
          padding: "48px 36px 96px",
        }}
      >
        {/* ---------- Introduction ---------- */}
        <h1
          id="introduction"
          style={{ fontSize: 32, fontWeight: 800, letterSpacing: "-0.03em", marginBottom: 12 }}
        >
          API Reference
        </h1>
        <p style={{ color: colors.textSecondary, fontSize: 15, lineHeight: 1.7, maxWidth: 640, marginBottom: 0 }}>
          The ONI Cortex API lets you programmatically manage tenants, collections, and retrieval
          queries. All endpoints return JSON. MCP-compatible clients can also connect via the
          SSE and HTTP transports.
        </p>

        {/* ---------- Base URL ---------- */}
        <SectionHeading id="base-url">Base URL</SectionHeading>
        <CodeBlock title="Production">{`https://cortex.oni.bot`}</CodeBlock>
        <p style={{ color: colors.textSecondary, fontSize: 13, marginTop: 10 }}>
          All REST paths below are relative to this base. MCP transport endpoints include the
          tenant ID in the path.
        </p>

        {/* ---------- Authentication ---------- */}
        <SectionHeading id="authentication">Authentication</SectionHeading>
        <p style={{ color: colors.textSecondary, fontSize: 14, lineHeight: 1.7 }}>
          Authenticated endpoints require an API key. On signup you receive two keys:
        </p>
        <ul style={{ color: colors.textSecondary, fontSize: 14, lineHeight: 1.8, paddingLeft: 20 }}>
          <li>
            <Code>oni_live_*</Code> — production key
          </li>
          <li>
            <Code>oni_test_*</Code> — test / sandbox key
          </li>
        </ul>
        <p style={{ color: colors.textSecondary, fontSize: 14, lineHeight: 1.7, marginTop: 12 }}>
          Pass the key in <strong style={{ color: colors.textPrimary }}>either</strong> of these ways:
        </p>

        <CodeBlock title="Authorization Header">{`Authorization: Bearer oni_live_abc123...`}</CodeBlock>
        <CodeBlock title="Query Parameter">{`GET /api/v1/me?key=oni_live_abc123...`}</CodeBlock>

        <p style={{ color: colors.textSecondary, fontSize: 13, marginTop: 14 }}>
          Public endpoints (<Code>/health</Code>, <Code>/api/v1/auth/signup</Code>) do not require
          authentication.
        </p>

        {/* ---------- Plan Tiers ---------- */}
        <SectionHeading id="plan-tiers">Plan Tiers</SectionHeading>
        <p style={{ color: colors.textSecondary, fontSize: 14, lineHeight: 1.7, marginBottom: 16 }}>
          Each tenant is assigned a plan that governs resource limits. You can select a plan at
          signup or upgrade later via the billing portal.
        </p>

        <div style={{ overflowX: "auto" }}>
          <table
            style={{
              width: "100%",
              borderCollapse: "collapse",
              fontSize: 13,
              fontFamily: mono,
            }}
          >
            <thead>
              <tr
                style={{
                  textAlign: "left",
                  color: colors.textSecondary,
                  borderBottom: `1px solid ${colors.border}`,
                }}
              >
                <th style={{ padding: "10px 12px" }}>Plan</th>
                <th style={{ padding: "10px 12px" }}>Collections</th>
                <th style={{ padding: "10px 12px" }}>Vectors</th>
                <th style={{ padding: "10px 12px" }}>Queries / Day</th>
              </tr>
            </thead>
            <tbody>
              {([
                ["free", "1", "10,000", "500"],
                ["pro", "5", "250,000", "10,000"],
                ["team", "25", "1,000,000", "50,000"],
                ["business", "100", "5,000,000", "200,000"],
                ["enterprise", "Unlimited", "Unlimited", "Unlimited"],
              ] as const).map(([plan, cols, vecs, queries]) => (
                <tr
                  key={plan}
                  style={{
                    borderBottom: `1px solid ${colors.border}`,
                  }}
                >
                  <td style={{ padding: "10px 12px", color: colors.accent, fontWeight: 600 }}>{plan}</td>
                  <td style={{ padding: "10px 12px", color: colors.textPrimary }}>{cols}</td>
                  <td style={{ padding: "10px 12px", color: colors.textPrimary }}>{vecs}</td>
                  <td style={{ padding: "10px 12px", color: colors.textPrimary }}>{queries}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* ================================================================
         *  ENDPOINTS
         * ================================================================*/}

        <SectionHeading id="signup">Sign Up</SectionHeading>
        <EndpointCard
          method="POST"
          path="/api/v1/auth/signup"
          description="Register a new tenant. Creates the account, generates live and test API keys, provisions a default collection, and sends a welcome email."
          auth="None"
          requestBody={
            <>
              <Field name="name" type="string" required>
                Display name
              </Field>
              <Field name="email" type="string" required>
                Valid email address
              </Field>
              <Field name="password" type="string" required>
                Account password
              </Field>
              <Field name="plan" type="string">
                {`One of: free (default), pro, team, business, enterprise`}
              </Field>
            </>
          }
          responseExample={JSON.stringify(
            {
              tenant_id: "tn_8f3a1b2c",
              name: "Acme Corp",
              email: "dev@acme.com",
              plan: "free",
              api_key_live: "oni_live_a1b2c3d4e5f6...",
              api_key_test: "oni_test_f6e5d4c3b2a1...",
              mcp_url: "https://cortex.oni.bot/t/tn_8f3a1b2c/sse",
            },
            null,
            2,
          )}
          responseTitle="201 Created"
        />

        <SectionHeading id="me">Get Current Tenant</SectionHeading>
        <EndpointCard
          method="GET"
          path="/api/v1/me"
          description="Return the authenticated tenant's profile including plan, collection count, today's usage, and plan limits."
          auth="API Key (Bearer token or query param)"
          responseExample={JSON.stringify(
            {
              tenant_id: "tn_8f3a1b2c",
              name: "Acme Corp",
              email: "dev@acme.com",
              plan: "pro",
              collections: 3,
              usage: {
                queries_today: 142,
                queries_limit: 10000,
              },
              limits: {
                collections: 5,
                vectors: 250000,
                queries_per_day: 10000,
              },
            },
            null,
            2,
          )}
          responseTitle="200 OK"
        />

        <SectionHeading id="rotate-key">Rotate API Keys</SectionHeading>
        <EndpointCard
          method="POST"
          path="/api/v1/me/rotate-key"
          description="Invalidate the current API keys and generate a new live / test pair. A confirmation email is sent to the tenant's address. The old keys stop working immediately."
          auth="API Key (Bearer token or query param)"
          responseExample={JSON.stringify(
            {
              api_key_live: "oni_live_new_key_here...",
              api_key_test: "oni_test_new_key_here...",
              message: "API keys rotated successfully",
            },
            null,
            2,
          )}
          responseTitle="200 OK"
        />

        <SectionHeading id="list-collections">List Collections</SectionHeading>
        <EndpointCard
          method="GET"
          path="/api/v1/collections"
          description="Return all collections belonging to the authenticated tenant. Each entry includes the Qdrant collection name used internally."
          auth="API Key (Bearer token or query param)"
          responseExample={JSON.stringify(
            [
              {
                id: "col_1a2b3c",
                collection_name: "default",
                data_type: "code",
                vector_count: 1024,
                qdrant_collection: "tn_8f3a1b2c_default",
              },
              {
                id: "col_4d5e6f",
                collection_name: "docs",
                data_type: "markdown",
                vector_count: 512,
                qdrant_collection: "tn_8f3a1b2c_docs",
              },
            ],
            null,
            2,
          )}
          responseTitle="200 OK"
        />

        <SectionHeading id="create-collection">Create Collection</SectionHeading>
        <EndpointCard
          method="POST"
          path="/api/v1/collections"
          description="Create a new collection under the authenticated tenant. The number of collections is limited by the tenant's plan tier."
          auth="API Key (Bearer token or query param)"
          requestBody={
            <>
              <Field name="collection_name" type="string" required>
                Unique name within this tenant
              </Field>
              <Field name="data_type" type="string">
                {`Content type hint — e.g. "code" (default), "markdown", "text", "json"`}
              </Field>
            </>
          }
          responseExample={JSON.stringify(
            {
              id: "col_7g8h9i",
              collection_name: "knowledge-base",
              data_type: "markdown",
              vector_count: 0,
              qdrant_collection: "tn_8f3a1b2c_knowledge-base",
            },
            null,
            2,
          )}
          responseTitle="201 Created"
        />

        <SectionHeading id="health">Health Check</SectionHeading>
        <EndpointCard
          method="GET"
          path="/health"
          description="Lightweight health probe for load balancers and uptime monitors. Always returns HTTP 200 when the service is running."
          auth="None"
          responseExample={JSON.stringify(
            {
              status: "ok",
              service: "oni-cortex",
            },
            null,
            2,
          )}
          responseTitle="200 OK"
        />

        {/* ================================================================
         *  MCP TRANSPORT
         * ================================================================*/}

        <SectionHeading id="mcp-sse">MCP SSE Transport</SectionHeading>
        <EndpointCard
          method="SSE"
          path="/t/{tenant_id}/sse"
          description="Server-Sent Events transport for the Model Context Protocol. Connect an MCP-compatible client (e.g. Claude Desktop, Cursor, Windsurf) to this endpoint to stream tool calls and retrieval results in real time."
          auth="API Key (query param ?key=)"
        >
          <div style={{ marginTop: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: colors.textSecondary, marginBottom: 8 }}>
              Path Parameters
            </div>
            <Field name="tenant_id" type="string" required>
              Your tenant ID (returned at signup)
            </Field>
          </div>
          <CodeBlock title="Example — Claude Desktop config (claude_desktop_config.json)">{`{
  "mcpServers": {
    "oni-cortex": {
      "url": "https://cortex.oni.bot/t/tn_8f3a1b2c/sse?key=oni_live_..."
    }
  }
}`}</CodeBlock>
        </EndpointCard>

        <SectionHeading id="mcp-http">MCP HTTP Transport</SectionHeading>
        <EndpointCard
          method="POST"
          path="/t/{tenant_id}/mcp"
          description="Stateless HTTP transport for the Model Context Protocol. Accepts a single MCP JSON-RPC request and returns the response. Use this when SSE is not supported by your client or infrastructure."
          auth="API Key (Bearer token or query param ?key=)"
        >
          <div style={{ marginTop: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: colors.textSecondary, marginBottom: 8 }}>
              Path Parameters
            </div>
            <Field name="tenant_id" type="string" required>
              Your tenant ID (returned at signup)
            </Field>
          </div>
          <CodeBlock title="Example Request">{`POST /t/tn_8f3a1b2c/mcp HTTP/1.1
Authorization: Bearer oni_live_...
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "search",
    "arguments": {
      "query": "How does authentication work?",
      "collection": "default",
      "top_k": 5
    }
  }
}`}</CodeBlock>
          <CodeBlock title="Example Response">{`{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "## Auth Middleware\\nRequests are authenticated via API key..."
      }
    ]
  }
}`}</CodeBlock>
        </EndpointCard>

        {/* ---------- Error Codes ---------- */}
        <SectionHeading id="errors">Error Responses</SectionHeading>
        <p style={{ color: colors.textSecondary, fontSize: 14, lineHeight: 1.7, marginBottom: 16 }}>
          All errors follow a consistent JSON shape:
        </p>
        <CodeBlock title="Error format">{`{
  "detail": "Human-readable error message"
}`}</CodeBlock>

        <div style={{ overflowX: "auto", marginTop: 16 }}>
          <table
            style={{
              width: "100%",
              borderCollapse: "collapse",
              fontSize: 13,
              fontFamily: mono,
            }}
          >
            <thead>
              <tr
                style={{
                  textAlign: "left",
                  color: colors.textSecondary,
                  borderBottom: `1px solid ${colors.border}`,
                }}
              >
                <th style={{ padding: "10px 12px" }}>Status</th>
                <th style={{ padding: "10px 12px" }}>Meaning</th>
              </tr>
            </thead>
            <tbody>
              {([
                ["400", "Bad request — invalid plan name, malformed body, etc."],
                ["401", "Missing or invalid API key"],
                ["403", "Plan limit reached (e.g. max collections)"],
                ["409", "Conflict — email already registered"],
                ["500", "Internal server error"],
              ] as const).map(([code, desc]) => (
                <tr key={code} style={{ borderBottom: `1px solid ${colors.border}` }}>
                  <td style={{ padding: "10px 12px", color: "#ef4444", fontWeight: 600 }}>{code}</td>
                  <td style={{ padding: "10px 12px", color: colors.textPrimary }}>{desc}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* ---------- Footer ---------- */}
        <div
          style={{
            marginTop: 64,
            paddingTop: 24,
            borderTop: `1px solid ${colors.border}`,
            color: colors.textSecondary,
            fontSize: 12,
          }}
        >
          ONI Cortex API v0.1.0 — https://cortex.oni.bot
        </div>
      </main>
    </div>
  );
}
