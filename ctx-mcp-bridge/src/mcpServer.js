import process from "node:process";
import fs from "node:fs";
import path from "node:path";
import { execSync } from "node:child_process";
import { createServer } from "node:http";
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { CallToolRequestSchema, ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";
import { loadAnyAuthEntry, loadAuthEntry, readConfig, saveAuthEntry } from "./authConfig.js";
import { maybeRemapToolArgs, maybeRemapToolResult } from "./resultPathMapping.js";
import * as oauthHandler from "./oauthHandler.js";

function debugLog(message) {
  try {
    const text = typeof message === "string" ? message : String(message);
    console.error(text);
    const dest = process.env.CTXCE_DEBUG_LOG;
    if (dest) {
      fs.appendFileSync(dest, `${new Date().toISOString()} ${text}\n`, "utf8");
    }
  } catch {
  }
}

async function sendSessionDefaults(client, payload, label) {
  if (!client) {
    return;
  }
  try {
    await client.callTool({
      name: "set_session_defaults",
      arguments: payload,
    });
  } catch (err) {
    // eslint-disable-next-line no-console
    console.error(`[ctxce] Failed to call set_session_defaults on ${label}:`, err);
  }
}
function dedupeTools(tools) {
  const seen = new Set();
  const out = [];
  for (const tool of tools) {
    const key = (tool && typeof tool.name === "string" && tool.name) || "";
    if (!key || seen.has(key)) {
      if (key === "" || key !== "set_session_defaults") {
        continue;
      }
      if (seen.has(key)) {
        continue;
      }
    }
    seen.add(key);
    out.push(tool);
  }
  return out;
}

async function listMemoryTools(client) {
  if (!client) {
    return [];
  }
  try {
    const remote = await client.listTools();
    return Array.isArray(remote?.tools) ? remote.tools.slice() : [];
  } catch (err) {
    debugLog("[ctxce] Error calling memory tools/list: " + String(err));
    return [];
  }
}

function withTimeout(promise, ms, label) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) {
        return;
      }
      settled = true;
      const errorMessage =
        label != null
          ? `[ctxce] Timeout after ${ms}ms in ${label}`
          : `[ctxce] Timeout after ${ms}ms`;
      reject(new Error(errorMessage));
    }, ms);
    promise
      .then((value) => {
        if (settled) {
          return;
        }
        settled = true;
        clearTimeout(timer);
        resolve(value);
      })
      .catch((err) => {
        if (settled) {
          return;
        }
        settled = true;
        clearTimeout(timer);
        reject(err);
      });
  });
}

function getBridgeToolTimeoutMs() {
  try {
    const raw = process.env.CTXCE_TOOL_TIMEOUT_MSEC;
    if (!raw) {
      return 600000; // 10 minutes default for remote operations
    }
    const parsed = Number.parseInt(String(raw), 10);
    if (!Number.isFinite(parsed) || parsed <= 0) {
      return 600000;
    }
    return parsed;
  } catch {
    return 600000;
  }
}

function selectClientForTool(name, indexerClient, memoryClient) {
  if (!name) {
    return indexerClient;
  }
  const lowered = name.toLowerCase();
  // Route to memory server for any memory-prefixed tool
  if (memoryClient && lowered.startsWith("memory")) {
    return memoryClient;
  }
  return indexerClient;
}

function isSessionError(error) {
  try {
    const msg =
      (error && typeof error.message === "string" && error.message) ||
      (typeof error === "string" ? error : String(error || ""));
    if (!msg) {
      return false;
    }
    return (
      msg.includes("No valid session ID") ||
      msg.includes("Mcp-Session-Id header is required") ||
      msg.includes("Server not initialized") ||
      msg.includes("Session not found")
    );
  } catch {
    return false;
  }
}

/**
 * Detect actual backend auth rejection (from mcp_auth.py ValidationError).
 * These indicate the session is truly invalid on the backend, not just
 * an MCP SDK transport issue that can be fixed by reinit.
 */
function isAuthRejectionError(error) {
  try {
    const msg =
      (error && typeof error.message === "string" && error.message) ||
      (typeof error === "string" ? error : String(error || ""));
    if (!msg) {
      return false;
    }
    return (
      msg.includes("Invalid or expired session") ||
      msg.includes("Missing session for authorized operation") ||
      msg.includes("Not authenticated")
    );
  } catch {
    return false;
  }
}

/**
 * Format an auth rejection error with actionable information for users.
 * Includes the backend URL and a hint to sign in via VS Code command palette.
 */
function formatAuthRejectionError(originalError, backendUrl) {
  const originalMsg =
    (originalError && typeof originalError.message === "string" && originalError.message) ||
    (typeof originalError === "string" ? originalError : String(originalError || "Unknown auth error"));

  const serverInfo = backendUrl ? ` (server: ${backendUrl})` : "";
  const hint = "Run 'Context Engine: Sign In' from the VS Code command palette to authenticate.";

  return `Authentication failed${serverInfo}: ${originalMsg}. ${hint}`;
}

/**
 * Emit a special log line that the VS Code extension can detect to show a notification toast.
 * Format: [ctxce:auth-error] JSON payload
 */
function emitAuthErrorNotification(backendUrl, originalError) {
  const payload = {
    type: "auth_rejection",
    backend: backendUrl || "unknown",
    message: String(originalError?.message || originalError || "Authentication failed"),
    hint: "Run 'Context Engine: Sign In' from the VS Code command palette",
  };
  // This special prefix allows the VS Code extension to detect auth errors in stderr
  debugLog(`[ctxce:auth-error] ${JSON.stringify(payload)}`);
}

function getBridgeRetryAttempts() {
  try {
    const raw = process.env.CTXCE_TOOL_RETRY_ATTEMPTS;
    if (!raw) {
      return 3; // 3 attempts for better reliability on remote
    }
    const parsed = Number.parseInt(String(raw), 10);
    if (!Number.isFinite(parsed) || parsed <= 0) {
      return 1;
    }
    return parsed;
  } catch {
    return 3;
  }
}

function getBridgeRetryDelayMs() {
  try {
    const raw = process.env.CTXCE_TOOL_RETRY_DELAY_MSEC;
    if (!raw) {
      return 1000; // 1 second delay between retries for remote
    }
    const parsed = Number.parseInt(String(raw), 10);
    if (!Number.isFinite(parsed) || parsed < 0) {
      return 0;
    }
    return parsed;
  } catch {
    return 1000;
  }
}

function isTransientToolError(error) {
  try {
    const msg =
      (error && typeof error.message === "string" && error.message) ||
      (typeof error === "string" ? error : String(error || ""));
    if (!msg) {
      return false;
    }
    const lower = msg.toLowerCase();

    if (
      lower.includes("timed out") ||
      lower.includes("timeout") ||
      lower.includes("time-out")
    ) {
      return true;
    }

    if (
      lower.includes("econnreset") ||
      lower.includes("econnrefused") ||
      lower.includes("etimedout") ||
      lower.includes("enotfound") ||
      lower.includes("ehostunreach") ||
      lower.includes("enetunreach")
    ) {
      return true;
    }

    if (
      lower.includes("bad gateway") ||
      lower.includes("gateway timeout") ||
      lower.includes("service unavailable") ||
      lower.includes(" 502 ") ||
      lower.includes(" 503 ") ||
      lower.includes(" 504 ")
    ) {
      return true;
    }

    if (lower.includes("network error")) {
      return true;
    }

    if (typeof error.code === "number" && error.code === -32001 && !isSessionError(error)) {
      return true;
    }
    if (
      typeof error.code === "string" &&
      error.code.toLowerCase &&
      error.code.toLowerCase().includes("timeout")
    ) {
      return true;
    }

    return false;
  } catch {
    return false;
  }
}
// MCP stdio server implemented using the official MCP TypeScript SDK.
// Acts as a low-level proxy for tools, forwarding tools/list and tools/call
// to the remote qdrant-indexer MCP server while adding a local `ping` tool.

const ADMIN_SESSION_COOKIE_NAME = "ctxce_session";
const SLUGGED_REPO_RE = /.+-[0-9a-f]{16}(?:_old)?$/i;
const BRIDGE_STATE_TOKEN = (process.env.CTXCE_BRIDGE_STATE_TOKEN || "").trim();

function getHostname(candidate) {
  try {
    const url = new URL(candidate);
    return url.hostname;
  } catch {
    return "";
  }
}

function normalizeBackendUrl(candidate) {
  const trimmed = (candidate || "").trim();
  if (!trimmed) {
    return "";
  }
  try {
    const parsed = new URL(trimmed);
    if (parsed.protocol && parsed.host) {
      return `${parsed.protocol}//${parsed.host}`;
    }
  } catch {
    // ignore parse failures
  }
  return trimmed.replace(/\/+$/, "");
}

function resolveAuthBackendContext(indexerUrl, memoryUrl) {
  const envBackend = normalizeBackendUrl(process.env.CTXCE_AUTH_BACKEND_URL || "");
  if (envBackend) {
    return { backendUrl: envBackend, source: "CTXCE_AUTH_BACKEND_URL" };
  }

  // If no env override, try to find a saved session.
  // We prefer one that matches the host of indexer or memory URL if they look like backend roots.
  const targetHosts = new Set();
  const ih = getHostname(indexerUrl);
  if (ih) {
    targetHosts.add(ih);
  }
  const mh = getHostname(memoryUrl);
  if (mh) {
    targetHosts.add(mh);
  }

  if (targetHosts.size > 0) {
    const all = readConfig();
    const backends = Object.keys(all);
    for (const backendUrl of backends) {
      const bh = getHostname(backendUrl);
      if (bh && targetHosts.has(bh)) {
        return { backendUrl, source: "auth_entry_host_match" };
      }
    }
  }

  try {
    const any = loadAnyAuthEntry();
    const stored = normalizeBackendUrl(any?.backendUrl || "");
    if (stored) {
      return { backendUrl: stored, source: "auth_entry" };
    }
  } catch {
    // ignore auth config read failures
  }
  return { backendUrl: "", source: "" };
}

async function fetchBridgeCollectionState({
  workspace,
  collection,
  sessionId,
  repoName,
  bridgeStateToken,
  backendHint,
  uploadServiceUrl,
}) {
  try {
    if (!uploadServiceUrl) {
      debugLog("[ctxce] Skipping bridge/state fetch: no upload endpoint configured.");
      return null;
    }
    const url = new URL("/bridge/state", uploadServiceUrl);
    // ...
    if (collection && collection.trim()) {
      url.searchParams.set("collection", collection.trim());
    } else if (workspace && workspace.trim()) {
      url.searchParams.set("workspace", workspace.trim());
    }
    if (repoName && repoName.trim()) {
      url.searchParams.set("repo_name", repoName.trim());
    }

    const headers = {
      Accept: "application/json",
    };
    if (bridgeStateToken && bridgeStateToken.trim()) {
      headers["X-Bridge-State-Token"] = bridgeStateToken.trim();
    }
    if (sessionId) {
      headers.Cookie = `${ADMIN_SESSION_COOKIE_NAME}=${sessionId}`;
    }

    debugLog(`[ctxce] Fetching bridge/state from ${url.toString()} (repo=${repoName || "<none>"}).`);
    const resp = await fetch(url, {
      method: "GET",
      headers,
    });
    if (!resp.ok) {
      if (resp.status === 401 || resp.status === 403) {
        debugLog(
          `[ctxce] /bridge/state responded ${resp.status}; missing or invalid token/session, marking local session as expired.`,
        );
        if (backendHint) {
          try {
            const entry = loadAuthEntry(backendHint);
            if (entry) {
              saveAuthEntry(backendHint, { ...entry, expiresAt: 1 });
            }
          } catch {
            // ignore failures
          }
        }
        return null;
      }
      throw new Error(`bridge/state responded ${resp.status}`);
    }
    debugLog(`[ctxce] bridge/state responded ${resp.status}`);
    const data = await resp.json();
    return data && typeof data === "object" ? data : null;
  } catch (err) {
    debugLog("[ctxce] Failed to fetch /bridge/state: " + String(err));
    return null;
  }
}

async function createBridgeServer(options) {
  const workspace = options.workspace || process.cwd();
  const indexerUrl = options.indexerUrl;
  const memoryUrl = options.memoryUrl;

  const config = loadConfig(workspace);
  const defaultCollection =
    config && typeof config.default_collection === "string"
      ? config.default_collection
      : null;
  const defaultMode =
    config && typeof config.default_mode === "string" ? config.default_mode : null;
  const defaultUnder =
    config && typeof config.default_under === "string" ? config.default_under : null;

  debugLog(
    `[ctxce] MCP low-level stdio bridge starting: workspace=${workspace}, indexerUrl=${indexerUrl}`,
  );

  if (defaultCollection) {
    // eslint-disable-next-line no-console
    console.error(
      `[ctxce] Using default collection from ctx_config.json: ${defaultCollection}`,
    );
  }

  let indexerClient = null;
  let memoryClient = null;

  // Derive a simple session identifier for this bridge process. In the
  // future this can be made user-aware (e.g. from auth), but for now we
  // keep it deterministic per workspace to help the indexer reuse
  // session-scoped defaults.
  const {
    backendUrl: authBackendUrl,
    source: authBackendSource,
  } = resolveAuthBackendContext(indexerUrl, memoryUrl);

  const uploadServiceUrl = authBackendUrl;
  const uploadAuthBackend = authBackendUrl;

  if (uploadServiceUrl) {
    debugLog(`[ctxce] Upload/auth backend resolved from ${authBackendSource}: ${uploadServiceUrl}`);
  } else {
    debugLog("[ctxce] No auth backend detected; bridge/state overrides disabled.");
  }

  const explicitSession = process.env.CTXCE_SESSION_ID || "";
  const authBackendEnv = (process.env.CTXCE_AUTH_BACKEND_URL || "").trim();
  let backendHint = authBackendEnv || uploadAuthBackend || "";
  let sessionId = explicitSession;

  function sessionFromEntry(entry) {
    if (!entry || typeof entry.sessionId !== "string" || !entry.sessionId) {
      return "";
    }
    const expiresAt = entry.expiresAt;
    if (
      typeof expiresAt === "number" &&
      Number.isFinite(expiresAt) &&
      expiresAt > 0 &&
      expiresAt < Math.floor(Date.now() / 1000)
    ) {
      debugLog("[ctxce] Stored auth session appears expired; please run `ctxce auth login` again.");
      return "";
    }
    return entry.sessionId;
  }

  function findSavedSession(backends) {
    for (const backend of backends) {
      const trimmed = (backend || "").trim();
      if (!trimmed) {
        continue;
      }
      try {
        const entry = loadAuthEntry(trimmed);
        const session = sessionFromEntry(entry);
        if (session) {
          backendHint = trimmed;
          return session;
        }
      } catch {
        // ignore lookup failures
      }
    }
    try {
      const any = loadAnyAuthEntry();
      const session = any ? sessionFromEntry(any.entry) : "";
      if (session && any?.backendUrl) {
        backendHint = any.backendUrl;
        return session;
      }
    } catch {
      // ignore lookup failures
    }
    return "";
  }

  function resolveSessionId() {
    const explicit = (process.env.CTXCE_SESSION_ID || "").trim();
    if (explicit) {
      return explicit;
    }
    return findSavedSession([backendHint, uploadAuthBackend, authBackendEnv]);
  }

  if (!sessionId) {
    sessionId = resolveSessionId();
  }

  // Only fall back to deterministic session if auth is not configured
  // If auth backend is configured but no session found, log warning instead of creating deterministic session
  if (!sessionId) {
    if (authBackendUrl) {
      // Auth is configured but no valid session - don't use deterministic fallback
      debugLog(`[ctxce] WARNING: Auth backend configured (${authBackendUrl}) but no valid session found.`);
      debugLog("[ctxce] To authenticate, run 'Context Engine: Sign In' from the VS Code command palette, or run `ctxce auth login` from the terminal.");
      debugLog("[ctxce] Continuing with deterministic session for backward compatibility, but this may fail if backend requires auth.");
      // Emit notification for VS Code extension
      emitAuthErrorNotification(authBackendUrl, { message: "No valid session found - authentication required" });
      sessionId = `ctxce-${Buffer.from(workspace).toString("hex").slice(0, 24)}`;
    } else {
      // No auth configured - use deterministic session for local-only operation
      sessionId = `ctxce-${Buffer.from(workspace).toString("hex").slice(0, 24)}`;
    }
  }

  // Best-effort: inform the indexer of default collection and session.
  // If this fails we still proceed, falling back to per-call injection.
  const defaultsPayload = { session: sessionId };
  if (defaultCollection) {
    defaultsPayload.collection = defaultCollection;
  }

  // Include org context from auth entry if available (for org-scoped collection isolation)
  try {
    const authEntry = backendHint ? loadAuthEntry(backendHint) : null;
    if (authEntry && authEntry.org_id) {
      defaultsPayload.org_id = authEntry.org_id;
      defaultsPayload.org_slug = authEntry.org_slug;
    }
  } catch {
    // ignore auth entry lookup failures
  }

  const repoName = detectRepoName(workspace, config);

  try {
    const state = await fetchBridgeCollectionState({
      workspace,
      collection: defaultCollection,
      sessionId,
      repoName,
      bridgeStateToken: BRIDGE_STATE_TOKEN,
      backendHint,
      uploadServiceUrl,
    });
    if (state) {
      const serving = state.serving_collection || state.active_collection;
      if (serving) {
        defaultsPayload.collection = serving;
        if (!defaultCollection || defaultCollection !== serving) {
          debugLog(
            `[ctxce] Using serving collection from /bridge/state: ${serving}`,
          );
        }
      }
    }
  } catch (err) {
    debugLog("[ctxce] bridge/state lookup failed: " + String(err));
  }

  if (defaultMode) {
    defaultsPayload.mode = defaultMode;
  }
  if (defaultUnder) {
    defaultsPayload.under = defaultUnder;
  }

  async function initializeRemoteClients(forceRecreate = false) {
    if (!forceRecreate && indexerClient) {
      return;
    }

    if (forceRecreate) {
      debugLog("[ctxce] Reinitializing remote MCP clients after session error.");
      
      if (indexerClient) {
        try {
          await indexerClient.close();
        } catch {
          // ignore close errors
        }
        indexerClient = null;
      }
      if (memoryClient) {
        try {
          await memoryClient.close();
        } catch {
          // ignore close errors
        }
        memoryClient = null;
      }
    }

    let nextIndexerClient = null;
    try {
      const indexerTransport = new StreamableHTTPClientTransport(indexerUrl);
      const client = new Client(
        {
          name: "ctx-context-engine-bridge-http-client",
          version: "0.0.1",
        },
        {
          capabilities: {
            tools: {},
            resources: {},
            prompts: {},
          },
        },
      );
      await client.connect(indexerTransport);
      nextIndexerClient = client;
    } catch (err) {
      debugLog("[ctxce] Failed to connect MCP HTTP client to indexer: " + String(err));
      nextIndexerClient = null;
    }

    let nextMemoryClient = null;
    if (memoryUrl) {
      try {
        const memoryTransport = new StreamableHTTPClientTransport(memoryUrl);
        const client = new Client(
          {
            name: "ctx-context-engine-bridge-memory-client",
            version: "0.0.1",
          },
          {
            capabilities: {
              tools: {},
              resources: {},
              prompts: {},
            },
          },
        );
        await client.connect(memoryTransport);
        debugLog(`[ctxce] Connected memory MCP client: ${memoryUrl}`);
        nextMemoryClient = client;
      } catch (err) {
        debugLog("[ctxce] Failed to connect memory MCP client: " + String(err));
        nextMemoryClient = null;
      }
    }

    indexerClient = nextIndexerClient;
    memoryClient = nextMemoryClient;

    if (Object.keys(defaultsPayload).length > 1 && indexerClient) {
      await sendSessionDefaults(indexerClient, defaultsPayload, "indexer");
      if (memoryClient) {
        await sendSessionDefaults(memoryClient, defaultsPayload, "memory");
      }
    }
  }

  await initializeRemoteClients(false);

  const server = new Server( // TODO: marked as depreciated
    {
      name: "ctx-context-engine-bridge",
      version: "0.0.1",
    },
    {
      capabilities: {
        tools: {},
      },
    },
  );

  // tools/list → fetch tools from remote indexer
  server.setRequestHandler(ListToolsRequestSchema, async () => {
    let remote;
    try {
      debugLog("[ctxce] tools/list: fetching tools from indexer");
      await initializeRemoteClients(false);
      if (!indexerClient) {
        throw new Error("Indexer MCP client not initialized");
      }
      remote = await indexerClient.listTools();
    } catch (err) {
      debugLog("[ctxce] Error calling remote tools/list: " + String(err));
      const memoryToolsFallback = await listMemoryTools(memoryClient);
      const toolsFallback = dedupeTools([...memoryToolsFallback]);
      return { tools: toolsFallback };
    }

    try {
      const toolNames =
        remote && Array.isArray(remote.tools)
          ? remote.tools.map((t) => (t && typeof t.name === "string" ? t.name : "<unnamed>"))
          : [];
      debugLog("[ctxce] tools/list remote result tools: " + JSON.stringify(toolNames));
    } catch (err) {
      debugLog("[ctxce] tools/list remote result: <unserializable> " + String(err));
    }

    const indexerTools = Array.isArray(remote?.tools) ? remote.tools.slice() : [];
    const memoryTools = await listMemoryTools(memoryClient);
    const tools = dedupeTools([...indexerTools, ...memoryTools]);
    debugLog(`[ctxce] tools/list: returning ${tools.length} tools`);
    return { tools };
  });

  // tools/call → proxied to indexer or memory server
  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const params = request.params || {};
    const name = params.name;
    let args = params.arguments;

    debugLog(`[ctxce] tools/call: ${name || "<no-name>"}`);

    // Refresh session before each call; re-init clients if session changes.
    const freshSession = resolveSessionId() || sessionId;
    if (freshSession && freshSession !== sessionId) {
      sessionId = freshSession;
      try {
        await initializeRemoteClients(true);
      } catch (err) {
        debugLog("[ctxce] Failed to reinitialize clients after session refresh: " + String(err));
      }
    }
    if (sessionId && (args === undefined || args === null || typeof args === "object")) {
      const obj = args && typeof args === "object" ? { ...args } : {};
      if (!Object.prototype.hasOwnProperty.call(obj, "session")) {
        obj.session = sessionId;
      }
      args = obj;
    }

    args = maybeRemapToolArgs(name, args, workspace);

    if (name === "set_session_defaults") {
      const indexerResult = await indexerClient.callTool({ name, arguments: args });
      if (memoryClient) {
        try {
          await memoryClient.callTool({ name, arguments: args });
        } catch (err) {
          debugLog("[ctxce] Memory set_session_defaults failed: " + String(err));
        }
      }
      return indexerResult;
    }

    await initializeRemoteClients(false);

    const timeoutMs = getBridgeToolTimeoutMs();
    const maxAttempts = getBridgeRetryAttempts();
    const retryDelayMs = getBridgeRetryDelayMs();
    let sessionRetried = false;
    let lastError;

    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
      if (attempt > 0 && retryDelayMs > 0) {
        await new Promise((resolve) => setTimeout(resolve, retryDelayMs));
      }

      const targetClient = selectClientForTool(name, indexerClient, memoryClient);
      if (!targetClient) {
        throw new Error(`Tool ${name} not available on any configured MCP server`);
      }

      try {
        const result = await targetClient.callTool(
          {
            name,
            arguments: args,
          },
          undefined,
          { timeout: timeoutMs },
        );
        return maybeRemapToolResult(name, result, workspace);
      } catch (err) {
        lastError = err;

        if (isSessionError(err) && !sessionRetried) {
          debugLog(
            "[ctxce] tools/call: detected remote MCP session error; reinitializing clients and retrying once: " +
            String(err),
          );
          await initializeRemoteClients(true);
          sessionRetried = true;
          continue;
        }

        // Backend auth rejection (mcp_auth.py ValidationError) - expire local auth
        if (isAuthRejectionError(err)) {
          const serverUrl = backendHint || uploadServiceUrl || "unknown server";
          debugLog(
            `[ctxce] tools/call: backend auth rejection from ${serverUrl}; marking local session as expired: ` +
            String(err),
          );
          // Emit special notification for VS Code extension to detect and show toast
          emitAuthErrorNotification(serverUrl, err);
          if (backendHint) {
            try {
              const entry = loadAuthEntry(backendHint);
              if (entry) {
                saveAuthEntry(backendHint, { ...entry, expiresAt: 1 });
              }
            } catch {
              // ignore failures
            }
          }
          // Enhance error with actionable message before throwing
          if (!isTransientToolError(err) || attempt === maxAttempts - 1) {
            const enhancedMessage = formatAuthRejectionError(err, serverUrl);
            const enhancedError = new Error(enhancedMessage);
            enhancedError.cause = err;
            throw enhancedError;
          }
        }

        if (!isTransientToolError(err) || attempt === maxAttempts - 1) {
          throw err;
        }

        debugLog(
          `[ctxce] tools/call: transient error (attempt ${attempt + 1}/${maxAttempts}), retrying: ` +
          String(err),
        );
        // Loop will retry
      }
    }

    throw lastError || new Error("Unknown MCP tools/call error");
  });

  return server;
}

export async function runMcpServer(options) {
  const server = await createBridgeServer(options);
  const transport = new StdioServerTransport();
  await server.connect(transport);

  const exitOnStdinClose = process.env.CTXCE_EXIT_ON_STDIN_CLOSE !== "0";
  if (exitOnStdinClose) {
    const handleStdioClosed = () => {
      try {
        debugLog("[ctxce] Stdio transport closed; exiting MCP bridge process.");
      } catch {
        // ignore
      }
      // Allow any in-flight logs to flush, then exit.
      setTimeout(() => {
        process.exit(0);
      }, 10).unref();
    };

    if (process.stdin && typeof process.stdin.on === "function") {
      process.stdin.on("end", handleStdioClosed);
      process.stdin.on("close", handleStdioClosed);
      process.stdin.on("error", handleStdioClosed);
    }
  }
}

export async function runHttpMcpServer(options) {
  const server = await createBridgeServer(options);
  const port =
    typeof options.port === "number"
      ? options.port
      : Number.parseInt(process.env.CTXCE_HTTP_PORT || "30810", 10) || 30810;

  const transport = new StreamableHTTPServerTransport({
    sessionIdGenerator: undefined,
  });

  await server.connect(transport);

  // Build issuer URL for OAuth
  // Note: Local-only bridge uses 127.0.0.1. For remote access, this would need to be configurable.
  const issuerUrl = `http://127.0.0.1:${port}`;

  const httpServer = createServer((req, res) => {
    try {
      const url = req.url || "/";

      // Parse URL for query params
      const parsedUrl = new URL(url, `http://${req.headers.host || 'localhost'}`);

      // ================================================================
      // OAuth 2.0 Endpoints (RFC9728 Protected Resource Metadata + RFC7591)
      // ================================================================

      // OAuth metadata endpoint (RFC9728)
      if (parsedUrl.pathname === "/.well-known/oauth-authorization-server") {
        oauthHandler.handleOAuthMetadata(req, res, issuerUrl);
        return;
      }

      // OAuth Dynamic Client Registration endpoint (RFC7591)
      if (parsedUrl.pathname === "/oauth/register" && req.method === "POST") {
        oauthHandler.handleOAuthRegister(req, res);
        return;
      }

      // OAuth authorize endpoint
      if (parsedUrl.pathname === "/oauth/authorize") {
        oauthHandler.handleOAuthAuthorize(req, res, parsedUrl.searchParams);
        return;
      }

      // Store session endpoint (helper for login page)
      if (parsedUrl.pathname === "/oauth/store-session" && req.method === "POST") {
        oauthHandler.handleOAuthStoreSession(req, res);
        return;
      }

      // OAuth token endpoint
      if (parsedUrl.pathname === "/oauth/token" && req.method === "POST") {
        oauthHandler.handleOAuthToken(req, res);
        return;
      }

      // ================================================================
      // MCP Endpoint
      // ================================================================

      // Check Bearer token for MCP endpoint (accept /mcp and /mcp/ for compatibility)
      if (parsedUrl.pathname === "/mcp" || parsedUrl.pathname === "/mcp/") {
        const authHeader = req.headers["authorization"] || "";
        const bearerToken = authHeader.startsWith("Bearer ") ? authHeader.slice(7) : null;

        // ----------------------------------------------------------------
        // AUTHENTICATION DESIGN: Permissive by default for backward compatibility
        // ----------------------------------------------------------------
        // The condition `bearerToken && hasTokenStore()` is INTENTIONALLY permissive:
        //
        // 1. PRE-EXISTING USERS (v3.0.0, local/dev mode):
        //    - No OAuth flow occurs → tokenStore remains empty
        //    - hasTokenStore() returns false → auth check skipped entirely
        //    - Requests proceed without authentication (local dev experience)
        //
        // 2. SAAS PLATFORM USERS (multi-tenant):
        //    - User completes OAuth flow → token stored in tokenStore
        //    - hasTokenStore() returns true → bearer token validation required
        //    - Invalid/missing tokens are rejected with 401
        //
        // WHY NOT `hasTokenStore() && !bearerToken` (require token when store exists)?
        //    - Mixed environments: Some clients may be local (no auth) while others
        //      are authenticated. Requiring auth globally after first login would
        //      break local dev workflows in hybrid setups.
        //    - The current design: "validate if provided, but don't require"
        //
        // SECURITY NOTE: If strict authentication is required for all clients once
        // any user authenticates, add an environment flag like CTXCE_REQUIRE_AUTH=1
        // and check it here to enforce bearer tokens regardless of token store state.
        // ----------------------------------------------------------------
        if (bearerToken && oauthHandler.hasTokenStore()) {
          const sessionId = oauthHandler.lookupToken(bearerToken);
          if (!sessionId) {
            // Token provided but invalid - reject
            res.writeHead(401, { "Content-Type": "application/json" });
            res.end(JSON.stringify({ jsonrpc: "2.0", error: { code: -32000, message: "Invalid or expired bearer token" }, id: null }));
            return;
          }
        }

        if (req.method !== "POST") {
          res.statusCode = 405;
          res.setHeader("Content-Type", "application/json");
          res.end(
            JSON.stringify({
              jsonrpc: "2.0",
              error: { code: -32000, message: "Method not allowed" },
              id: null,
            }),
          );
          return;
        }

        const MAX_BODY_SIZE = 10 * 1024 * 1024; // 10MB
        let body = "";
        let bodyLimitExceeded = false;
        req.on("data", (chunk) => {
          if (bodyLimitExceeded) return;
          body += chunk;
          if (body.length > MAX_BODY_SIZE) {
            bodyLimitExceeded = true;
            req.destroy();
            res.statusCode = 413;
            res.setHeader("Content-Type", "application/json");
            res.end(
              JSON.stringify({
                jsonrpc: "2.0",
                error: { code: -32000, message: "Request body too large" },
                id: null,
              }),
            );
          }
        });
        req.on("end", async () => {
          if (bodyLimitExceeded) return;
          let parsed;
          try {
            parsed = body ? JSON.parse(body) : {};
          } catch (err) {
            debugLog("[ctxce] Failed to parse HTTP MCP request body: " + String(err));
            res.statusCode = 400;
            res.setHeader("Content-Type", "application/json");
            res.end(
              JSON.stringify({
                jsonrpc: "2.0",
                error: { code: -32700, message: "Invalid JSON" },
                id: null,
              }),
            );
            return;
          }

          try {
            await transport.handleRequest(req, res, parsed);
          } catch (err) {
            debugLog("[ctxce] Error handling HTTP MCP request: " + String(err));
            if (!res.headersSent) {
              res.statusCode = 500;
              res.setHeader("Content-Type", "application/json");
              res.end(
                JSON.stringify({
                  jsonrpc: "2.0",
                  error: { code: -32603, message: "Internal server error" },
                  id: null,
                }),
              );
            }
          }
        });
        return;
      }

      // 404 for everything else
      res.statusCode = 404;
      res.setHeader("Content-Type", "application/json");
      res.end(
        JSON.stringify({
          jsonrpc: "2.0",
          error: { code: -32000, message: "Not found" },
          id: null,
        }),
      );
    } catch (err) {
      debugLog("[ctxce] Unexpected error in HTTP MCP server: " + String(err));
      if (!res.headersSent) {
        res.statusCode = 500;
        res.setHeader("Content-Type", "application/json");
        res.end(
          JSON.stringify({
            jsonrpc: "2.0",
            error: { code: -32603, message: "Internal server error" },
            id: null,
          }),
        );
      }
    }
  });

  // Bind to 127.0.0.1 only (localhost) for local-only OAuth security
  httpServer.listen(port, '127.0.0.1', () => {
    debugLog(`[ctxce] HTTP MCP bridge listening on 127.0.0.1:${port}`);
  });

  let shuttingDown = false;
  const shutdown = (signal) => {
    if (shuttingDown) return;
    shuttingDown = true;
    debugLog(`[ctxce] Received ${signal}; closing HTTP server (waiting for in-flight requests).`);
    httpServer.close(() => {
      debugLog("[ctxce] HTTP server closed.");
      process.exit(0);
    });
    const SHUTDOWN_TIMEOUT_MS = 5 * 60 * 1000; // 5 minutes for long MCP calls
    setTimeout(() => {
      debugLog("[ctxce] Forcing exit after shutdown timeout.");
      process.exit(1);
    }, SHUTDOWN_TIMEOUT_MS).unref();
  };

  process.on("SIGTERM", () => shutdown("SIGTERM"));
  process.on("SIGINT", () => shutdown("SIGINT"));
}

function loadConfig(startDir) {
  try {
    let dir = startDir;
    for (let i = 0; i < 5; i += 1) {
      const cfgPath = path.join(dir, "ctx_config.json");
      if (fs.existsSync(cfgPath)) {
        try {
          const raw = fs.readFileSync(cfgPath, "utf8");
          const parsed = JSON.parse(raw);
          if (parsed && typeof parsed === "object") {
            return parsed;
          }
        } catch (err) {
          // eslint-disable-next-line no-console
          console.error("[ctxce] Failed to parse ctx_config.json:", err);
          return null;
        }
      }
      const parent = path.dirname(dir);
      if (!parent || parent === dir) {
        break;
      }
      dir = parent;
    }
  } catch (err) {
    // eslint-disable-next-line no-console
    console.error("[ctxce] Error while loading ctx_config.json:", err);
  }
  return null;
}

function detectGitBranch(workspace) {
  try {
    const out = execSync("git rev-parse --abbrev-ref HEAD", {
      cwd: workspace,
      stdio: ["ignore", "pipe", "ignore"],
    });
    const name = out.toString("utf8").trim();
    return name || null;
  } catch {
    return null;
  }
}

function detectRepoName(workspace, config) {
  const envRepo =
    (process.env.CURRENT_REPO && process.env.CURRENT_REPO.trim()) ||
    (process.env.REPO_NAME && process.env.REPO_NAME.trim());
  if (envRepo) {
    return envRepo;
  }

  if (config) {
    const cfgRepo =
      (typeof config.repo_name === "string" && config.repo_name.trim()) ||
      (typeof config.default_repo === "string" && config.default_repo.trim());
    if (cfgRepo) {
      return cfgRepo;
    }
  }

  const leaf = workspace ? path.basename(workspace) : "";
  return leaf && SLUGGED_REPO_RE.test(leaf) ? leaf : null;
}

