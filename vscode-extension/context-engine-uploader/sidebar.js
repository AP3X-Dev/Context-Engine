const vscode = require('vscode');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const { getDefaultWindsurfMcpPath, getDefaultAugmentMcpPath, getDefaultAntigravityMcpPath, getDefaultCursorMcpPath } = require('./mcp_config');
const { checkAuthStatus } = require('./auth_utils');

function makeTreeItem(label, opts = {}) {
  const item = new vscode.TreeItem(label, opts.collapsibleState || vscode.TreeItemCollapsibleState.None);
  if (opts.description !== undefined) {
    item.description = opts.description;
  }
  if (opts.tooltip !== undefined) {
    item.tooltip = opts.tooltip;
  }
  if (opts.icon !== undefined) {
    item.iconPath = opts.icon;
  }
  if (opts.command !== undefined) {
    item.command = opts.command;
  }
  if (opts.contextValue !== undefined) {
    item.contextValue = opts.contextValue;
  }
  if (opts.profileId !== undefined) {
    item.id = opts.profileId;
  }
  return item;
}

function createProvider(getChildrenFn) {
  const emitter = new vscode.EventEmitter();
  return {
    onDidChangeTreeData: emitter.event,
    refresh: () => emitter.fire(undefined),
    getTreeItem: element => element,
    getChildren: async element => getChildrenFn(element),
  };
}

function resolveMcpMode(cfg) {
  try {
    const transportModeRaw = cfg.get('mcpTransportMode') || 'sse-remote';
    const serverModeRaw = cfg.get('mcpServerMode') || 'bridge';
    const transportMode = (typeof transportModeRaw === 'string' ? transportModeRaw.trim() : 'sse-remote') || 'sse-remote';
    const serverMode = (typeof serverModeRaw === 'string' ? serverModeRaw.trim() : 'bridge') || 'bridge';
    return `${serverMode}/${transportMode}`;
  } catch (_) {
    return 'unknown';
  }
}

function getWorkspaceRoot() {
  try {
    const folders = vscode.workspace.workspaceFolders;
    if (folders && folders.length) {
      return folders[0].uri.fsPath;
    }
  } catch (_) {
    // ignore
  }
  return undefined;
}

function pathExists(p, expectDir = false) {
  try {
    if (!p) {
      return false;
    }
    const stat = fs.statSync(p);
    return expectDir ? stat.isDirectory() : stat.isFile();
  } catch (_) {
    return false;
  }
}

function findConfigFile(bases, filename) {
  for (const base of bases) {
    if (!base) {
      continue;
    }
    const candidate = path.join(base, filename);
    if (pathExists(candidate)) {
      return candidate;
    }
  }
  return undefined;
}

const _authStatusCache = new Map();
const _AUTH_STATUS_TTL_MS = 30_000;
const _AUTH_STATUS_TIMEOUT_MS = 750;
const _AUTH_STATUS_MAX_ENTRIES = 100;

const _endpointReachableCache = new Map();
const _ENDPOINT_REACHABLE_TTL_MS = 15_000;
const _ENDPOINT_REACHABLE_TIMEOUT_MS = 750;
const _ENDPOINT_REACHABLE_MAX_ENTRIES = 100;

// Health status cache for status panel
const _healthStatusCache = new Map();
const _HEALTH_STATUS_TTL_MS = 10_000;
const _HEALTH_STATUS_TIMEOUT_MS = 1500;

/**
 * Probe a service health endpoint.
 * @param {string} url - Full URL to probe (e.g., http://localhost:8004/health)
 * @returns {Promise<{ok: boolean, latencyMs?: number, error?: string}>}
 */
async function probeHealthEndpoint(url) {
  const fetchFn = (typeof fetch === 'function' ? fetch : undefined);
  if (!fetchFn || !url) {
    return { ok: false, error: 'No fetch available or invalid URL' };
  }

  let timer;
  let controller;
  const start = Date.now();
  try {
    controller = (typeof AbortController === 'function') ? new AbortController() : undefined;
    if (controller) {
      timer = setTimeout(() => {
        try { controller.abort(); } catch (_) { }
      }, _HEALTH_STATUS_TIMEOUT_MS);
    }
    const res = await fetchFn(url, { method: 'GET', signal: controller ? controller.signal : undefined });
    const latencyMs = Date.now() - start;
    if (res && res.ok) {
      return { ok: true, latencyMs };
    }
    return { ok: false, error: `HTTP ${res.status}`, latencyMs };
  } catch (err) {
    return { ok: false, error: err && err.name === 'AbortError' ? 'Timeout' : 'Connection failed' };
  } finally {
    if (timer) {
      clearTimeout(timer);
    }
  }
}

/**
 * Get cached health status for a service.
 * @param {string} key - Cache key (e.g., 'backend', 'mcp-indexer', 'qdrant')
 * @param {string} url - Health endpoint URL
 * @returns {Promise<{ok: boolean, latencyMs?: number, error?: string}>}
 */
async function getCachedHealthStatus(key, url) {
  if (!url) {
    return { ok: false, error: 'Not configured' };
  }
  const now = Date.now();
  const cached = _healthStatusCache.get(key);
  if (cached && cached.ts && (now - cached.ts) < _HEALTH_STATUS_TTL_MS) {
    return cached.status;
  }
  const status = await probeHealthEndpoint(url);
  _healthStatusCache.set(key, { status, ts: now });
  return status;
}

function pruneCache(cache, ttlMs, maxEntries) {
  const now = Date.now();
  for (const [key, entry] of cache.entries()) {
    if (!entry.ts || (now - entry.ts) > ttlMs) {
      cache.delete(key);
    }
  }
  if (cache.size > maxEntries) {
    const entries = [...cache.entries()].sort((a, b) => (a[1].ts || 0) - (b[1].ts || 0));
    const toRemove = entries.slice(0, cache.size - maxEntries);
    for (const [key] of toRemove) {
      cache.delete(key);
    }
  }
}

async function probeEndpointReachable(endpoint) {
  const base = (endpoint || '').trim().replace(/\/+$/, '');
  if (!base) {
    return undefined;
  }

  const fetchFn = (typeof fetch === 'function' ? fetch : undefined);
  if (!fetchFn) {
    return undefined;
  }

  let timer;
  let controller;
  try {
    controller = (typeof AbortController === 'function') ? new AbortController() : undefined;
    if (controller) {
      timer = setTimeout(() => {
        try { controller.abort(); } catch (_) { }
      }, _ENDPOINT_REACHABLE_TIMEOUT_MS);
    }
    const res = await fetchFn(`${base}/health`, { method: 'GET', signal: controller ? controller.signal : undefined });
    if (!res) {
      return false;
    }
    return !!res.ok;
  } catch (_) {
    return false;
  } finally {
    if (timer) {
      clearTimeout(timer);
    }
  }
}

async function getCachedEndpointReachable(endpoint) {
  const key = (endpoint || '').trim();
  if (!key) {
    return undefined;
  }
  const now = Date.now();
  const cached = _endpointReachableCache.get(key);
  if (cached && cached.ts && (now - cached.ts) < _ENDPOINT_REACHABLE_TTL_MS) {
    return cached.reachable;
  }
  const reachable = await probeEndpointReachable(key);
  _endpointReachableCache.set(key, { reachable, ts: now });
  return reachable;
}

async function probeAuthEnabled(endpoint) {
  const base = (endpoint || '').trim().replace(/\/+$/, '');
  if (!base) {
    return undefined;
  }

  const fetchFn = (typeof fetch === 'function' ? fetch : undefined);
  if (!fetchFn) {
    return undefined;
  }

  let timer;
  let controller;
  try {
    controller = (typeof AbortController === 'function') ? new AbortController() : undefined;
    if (controller) {
      timer = setTimeout(() => {
        try { controller.abort(); } catch (_) { }
      }, _AUTH_STATUS_TIMEOUT_MS);
    }
    const res = await fetchFn(`${base}/auth/status`, { method: 'GET', signal: controller ? controller.signal : undefined });
    if (!res || !res.ok) {
      return undefined;
    }
    const body = await res.json();
    if (body && typeof body.enabled === 'boolean') {
      return body.enabled;
    }
    return undefined;
  } catch (_) {
    return undefined;
  } finally {
    if (timer) {
      clearTimeout(timer);
    }
  }
}

async function getCachedAuthEnabled(endpoint) {
  const key = (endpoint || '').trim();
  if (!key) {
    return undefined;
  }
  const now = Date.now();
  const cached = _authStatusCache.get(key);
  if (cached && cached.ts && (now - cached.ts) < _AUTH_STATUS_TTL_MS) {
    return cached.enabled;
  }
  const enabled = await probeAuthEnabled(key);
  _authStatusCache.set(key, { enabled, ts: now });
  return enabled;
}

const _authLoggedInCache = new Map();
const _AUTH_LOGGED_IN_TTL_MS = 10_000;

/**
 * Check if user is logged in to the configured endpoint.
 * Uses ctxce auth status to check session state.
 * Returns true if logged in (state === 'ok'), false otherwise.
 * @param {string} endpoint
 * @param {object} deps - needs spawn, resolveBridgeCliInvocation, getWorkspaceFolderPath
 */
async function getCachedAuthLoggedIn(endpoint, deps) {
  // Validate deps first before accessing any properties
  if (!deps || typeof deps.resolveBridgeCliInvocation !== 'function' || typeof deps.getWorkspaceFolderPath !== 'function' || typeof deps.spawn !== 'function') {
    return undefined;
  }
  const workspacePath = typeof deps.getWorkspaceFolderPath === 'function' ? deps.getWorkspaceFolderPath() || '' : '';
  const key = `${endpoint || ''}::${workspacePath}`;
  if (!endpoint) {
    return undefined;
  }
  const now = Date.now();
  const cached = _authLoggedInCache.get(key);
  if (cached && cached.ts && (now - cached.ts) < _AUTH_LOGGED_IN_TTL_MS) {
    return cached.loggedIn;
  }
  const statusDeps = {
    spawn: deps.spawn,
    resolveBridgeCliInvocation: deps.resolveBridgeCliInvocation,
    getWorkspaceFolderPath: deps.getWorkspaceFolderPath,
  };
  try {
    const status = await checkAuthStatus(endpoint, statusDeps);
    const loggedIn = status && status.state === 'ok';
    _authLoggedInCache.set(key, { loggedIn, ts: now });
    return loggedIn;
  } catch (error) {
    // Log error without throwing into UI
    const message = error instanceof Error ? error.message : String(error);
    if (typeof deps.log === 'function') {
      deps.log(`Failed to check auth status: ${message}`);
    }
    return undefined;
  }
}


async function probeBridgeAlive(port) {
  if (!port) return false;
  const fetchFn = (typeof fetch === 'function' ? fetch : undefined);
  if (!fetchFn) return false;
  try {
    const res = await fetchFn(`http://127.0.0.1:${port}/mcp`, {
      method: 'GET',
      headers: { 'Accept': 'application/json' }
    });
    // Bridge returns 405 for GET /mcp, which is fine, it means something is listening
    return res.status === 405 || res.ok;
  } catch (_) {
    return false;
  }
}

function register(context, deps) {
  const profiles = deps && deps.profiles;
  const getEffectiveConfig = deps && deps.getEffectiveConfig;
  const getResolvedTargetPath = deps && deps.getResolvedTargetPath;
  const getState = deps && deps.getState;
  const onboarding = deps && deps.onboarding;
  const resolveBridgeCliInvocation = deps && deps.resolveBridgeCliInvocation;
  const getWorkspaceFolderPath = deps && deps.getWorkspaceFolderPath;
  const spawn = deps && deps.spawn;
  const log = deps && deps.log;

  const providers = [];

  // Helper function to build auth menu items (Sign In / Sign Out)
  async function buildAuthMenuItem(endpoint, authDeps) {
    const isLoggedIn = await getCachedAuthLoggedIn(endpoint, authDeps);
    if (isLoggedIn) {
      return makeTreeItem('Sign Out', {
        icon: new vscode.ThemeIcon('sign-out'),
        command: { command: 'contextEngineUploader.authLogout', title: 'Sign Out' },
        tooltip: 'Sign out from the configured endpoint.',
      });
    } else {
      return makeTreeItem('Sign In', {
        icon: new vscode.ThemeIcon('account'),
        command: { command: 'contextEngineUploader.authLogin', title: 'Sign In' },
        tooltip: 'Runs ctxce auth login for the configured endpoint.',
      });
    }
  }

  const profilesProvider = createProvider(async element => {
    if (!profiles || typeof profiles.listProfiles !== 'function') {
      return [];
    }

    if (!element) {
      return [
        makeTreeItem('Active Profile', { collapsibleState: vscode.TreeItemCollapsibleState.Expanded, contextValue: 'ctxceProfilesActiveRoot' }),
        makeTreeItem('Manage Profiles', { collapsibleState: vscode.TreeItemCollapsibleState.Collapsed, contextValue: 'ctxceProfilesManageRoot' }),
      ];
    }

    if (element.contextValue === 'ctxceProfilesActiveRoot') {
      const active = typeof profiles.getActiveProfileSummary === 'function' ? profiles.getActiveProfileSummary() : { id: undefined, name: undefined };
      const list = profiles.listProfiles();
      const items = [];

      items.push(makeTreeItem(`Current: ${active && active.id ? (active.name || active.id) : 'None'}`, {
        description: active && active.id ? active.id : '',
        icon: new vscode.ThemeIcon(active && active.id ? 'check' : 'circle-slash'),
        contextValue: 'ctxceProfilesCurrent',
      }));

      items.push(makeTreeItem('None (use VS Code settings)', {
        icon: new vscode.ThemeIcon(!active || !active.id ? 'check' : 'circle-slash'),
        command: {
          command: 'contextEngineUploader._setActiveProfile',
          title: 'Set Active Profile',
          arguments: [''],
        },
        contextValue: 'ProfilesChoice',
      }));

      for (const p of list) {
        const isActive = !!(active && active.id && p.id === active.id);
        items.push(makeTreeItem(p.name || p.id, {
          description: p.id,
          icon: new vscode.ThemeIcon(isActive ? 'check' : 'circle-outline'),
          command: {
            command: 'contextEngineUploader._setActiveProfile',
            title: 'Set Active Profile',
            arguments: [p.id],
          },
          contextValue: 'ProfileItem',
          profileId: p.id,
        }));
      }

      return items;
    }

    if (element.contextValue === 'ctxceProfilesManageRoot') {
      return [
        makeTreeItem('Setup Workspace', { icon: new vscode.ThemeIcon('rocket'), command: { command: 'contextEngineUploader.setupWorkspace', title: 'Setup Workspace' } }),
        makeTreeItem('Switch Profile', { icon: new vscode.ThemeIcon('sync'), command: { command: 'contextEngineUploader.switchProfile', title: 'Switch Profile' } }),
        makeTreeItem('Create Profile', { icon: new vscode.ThemeIcon('add'), command: { command: 'contextEngineUploader.createProfileFromCurrentSettings', title: 'Create Profile' } }),
        makeTreeItem('Rename Profile', { icon: new vscode.ThemeIcon('edit'), command: { command: 'contextEngineUploader.renameProfile', title: 'Rename Profile' } }),
        makeTreeItem('Duplicate Profile', { icon: new vscode.ThemeIcon('copy'), command: { command: 'contextEngineUploader.duplicateProfile', title: 'Duplicate Profile' } }),
        makeTreeItem('Delete Profile', { icon: new vscode.ThemeIcon('trash'), command: { command: 'contextEngineUploader.deleteProfile', title: 'Delete Profile' } }),
        makeTreeItem('Import Profiles', { icon: new vscode.ThemeIcon('cloud-download'), command: { command: 'contextEngineUploader.importProfiles', title: 'Import Profiles' } }),
        makeTreeItem('Export Profiles', { icon: new vscode.ThemeIcon('cloud-upload'), command: { command: 'contextEngineUploader.exportProfiles', title: 'Export Profiles' } }),
      ];
    }

    return [];
  });

  const statusProvider = createProvider(async () => {
    const cfg = getEffectiveConfig ? getEffectiveConfig() : vscode.workspace.getConfiguration('contextEngineUploader');
    const state = typeof getState === 'function' ? getState() : {};

    const endpoint = (() => {
      try { return (cfg.get('endpoint') || '').trim(); } catch (_) { return ''; }
    })();

    // Health endpoints configuration
    const backendUrl = endpoint ? `${endpoint.replace(/\/+$/, '')}/health` : '';
    const mcpIndexerPort = cfg.get('mcpIndexerPort') || 18003;
    const mcpIndexerUrl = `http://localhost:${mcpIndexerPort}/readyz`;
    const qdrantPort = cfg.get('qdrantPort') || 6333;
    const qdrantUrl = `http://localhost:${qdrantPort}/readyz`;

    // Probe health endpoints in parallel
    const [backendHealth, mcpHealth, qdrantHealth] = await Promise.all([
      backendUrl ? getCachedHealthStatus('backend', backendUrl) : { ok: false, error: 'Not configured' },
      getCachedHealthStatus('mcp-indexer', mcpIndexerUrl),
      getCachedHealthStatus('qdrant', qdrantUrl),
    ]);

    // Helper to get icon and description based on health
    const getHealthIcon = (health) => {
      if (health.ok) return new vscode.ThemeIcon('check', new vscode.ThemeColor('charts.green'));
      return new vscode.ThemeIcon('error', new vscode.ThemeColor('charts.red'));
    };
    const getHealthDesc = (health, label) => {
      if (health.ok) return `✓ ${label}`;
      return `✗ ${health.error || 'Unavailable'}`;
    };

    // Check if all systems are operational
    const allHealthy = backendHealth.ok && mcpHealth.ok && qdrantHealth.ok;

    // Build status items
    const items = [];

    // Show "All Systems Operational" banner when healthy
    if (allHealthy) {
      items.push(makeTreeItem('All Systems Operational', {
        description: '',
        icon: new vscode.ThemeIcon('verified-filled', new vscode.ThemeColor('charts.green')),
        tooltip: 'Backend, MCP Indexer, and Qdrant are all running.',
        contextValue: 'ctxceStatusAllHealthy'
      }));
    }

    // Backend health
    items.push(makeTreeItem('Backend', {
      description: getHealthDesc(backendHealth, 'Connected'),
      icon: getHealthIcon(backendHealth),
      tooltip: backendHealth.ok
        ? `Backend is healthy (${backendHealth.latencyMs}ms)`
        : `Backend unavailable: ${backendHealth.error}\nClick to configure endpoint.`,
      command: backendHealth.ok ? undefined : {
        command: 'workbench.action.openSettings',
        title: 'Configure Endpoint',
        arguments: ['contextEngineUploader.endpoint']
      },
      contextValue: 'ctxceStatusBackend'
    }));

    // MCP Indexer health
    items.push(makeTreeItem('MCP Indexer', {
      description: getHealthDesc(mcpHealth, 'Running'),
      icon: getHealthIcon(mcpHealth),
      tooltip: mcpHealth.ok
        ? `MCP Indexer is healthy (port ${mcpIndexerPort})`
        : `MCP Indexer unavailable: ${mcpHealth.error}\nEnsure MCP Indexer is running on port ${mcpIndexerPort}.`,
      command: mcpHealth.ok ? undefined : {
        command: 'contextEngineUploader.showUploadServiceLogs',
        title: 'Show Logs'
      },
      contextValue: 'ctxceStatusMcpIndexer'
    }));

    // Qdrant health
    items.push(makeTreeItem('Qdrant', {
      description: getHealthDesc(qdrantHealth, 'Running'),
      icon: getHealthIcon(qdrantHealth),
      tooltip: qdrantHealth.ok
        ? `Qdrant vector DB is healthy (port ${qdrantPort})`
        : `Qdrant unavailable: ${qdrantHealth.error}\nStart Qdrant with: docker compose up -d qdrant`,
      command: qdrantHealth.ok ? undefined : {
        command: 'contextEngineUploader.startSavedStack',
        title: 'Start Stack'
      },
      contextValue: 'ctxceStatusQdrant'
    }));

    // Last index timestamp (from state if available)
    const lastIndex = state && state.lastIndexTime
      ? new Date(state.lastIndexTime).toLocaleString()
      : 'Never';
    items.push(makeTreeItem('Last Index', {
      description: lastIndex,
      icon: new vscode.ThemeIcon('history'),
      tooltip: 'Last time the codebase was indexed.',
      contextValue: 'ctxceStatusLastIndex'
    }));

    return items;
  });

  const actionsProvider = createProvider(async (element) => {
    if (!element) {
      return [
        makeTreeItem('Settings', {
          icon: new vscode.ThemeIcon('settings-gear'),
          command: { command: 'contextEngineUploader.openSettings', title: 'Open Settings' },
          tooltip: 'Open Context Engine settings panel',
          contextValue: 'ctxceSettingsButton'
        }),
        makeTreeItem('Getting Started', {
          icon: new vscode.ThemeIcon('rocket'),
          collapsibleState: vscode.TreeItemCollapsibleState.Expanded,
          contextValue: 'ctxceActionsGettingStartedRoot'
        }),
        makeTreeItem('Indexing', {
          icon: new vscode.ThemeIcon('database'),
          collapsibleState: vscode.TreeItemCollapsibleState.Expanded,
          contextValue: 'ctxceActionsUploadRoot'
        }),
        makeTreeItem('MCP Integrations', {
          icon: new vscode.ThemeIcon('plug'),
          collapsibleState: vscode.TreeItemCollapsibleState.Collapsed,
          contextValue: 'ctxceActionsBridgeRoot'
        }),
        makeTreeItem('Prompt+', {
          icon: new vscode.ThemeIcon('sparkle'),
          collapsibleState: vscode.TreeItemCollapsibleState.Collapsed,
          contextValue: 'ctxceActionsUtilitiesRoot'
        }),
      ];
    }

    if (element.contextValue === 'ctxceActionsGettingStartedRoot') {
      const cfg = getEffectiveConfig ? getEffectiveConfig() : vscode.workspace.getConfiguration('contextEngineUploader');

      const endpoint = (() => {
        try { return (cfg.get('endpoint') || '').trim(); } catch (_) { return ''; }
      })();

      const endpointExplicitlyConfigured = (() => {
        try {
          const overrides = profiles && typeof profiles.getActiveProfileOverrides === 'function'
            ? profiles.getActiveProfileOverrides()
            : {};
          if (overrides && typeof overrides === 'object' && Object.prototype.hasOwnProperty.call(overrides, 'endpoint')) {
            return true;
          }
        } catch (_) {
        }
        try {
          const inspected = (cfg && typeof cfg.inspect === 'function') ? cfg.inspect('endpoint') : undefined;
          if (!inspected || typeof inspected !== 'object') {
            return false;
          }
          return inspected.workspaceFolderValue !== undefined || inspected.workspaceValue !== undefined || inspected.globalValue !== undefined;
        } catch (_) {
          return false;
        }
      })();

      const endpointReachable = endpoint ? await getCachedEndpointReachable(endpoint) : undefined;

      const resolvedTarget = typeof getResolvedTargetPath === 'function' ? getResolvedTargetPath() : undefined;
      const targetDescription = resolvedTarget && resolvedTarget.path ? resolvedTarget.path : '(unset)';
      const targetPath = resolvedTarget && resolvedTarget.path ? String(resolvedTarget.path) : '';
      const targetExists = pathExists(targetPath, true);
      const workspaceRoot = getWorkspaceRoot();
      const configSearchBases = [targetPath, workspaceRoot].filter(Boolean);
      const mcpConfigPath = findConfigFile(configSearchBases, '.mcp.json');
      const ctxConfigPath = findConfigFile(configSearchBases, 'ctx_config.json');

      const claudeEnabled = (() => {
        try { return !!cfg.get('mcpClaudeEnabled', true); } catch (_) { return true; }
      })();
      const windsurfEnabled = (() => {
        try { return !!cfg.get('mcpWindsurfEnabled', false); } catch (_) { return false; }
      })();
      const augmentEnabled = (() => {
        try { return !!cfg.get('mcpAugmentEnabled', false); } catch (_) { return false; }
      })();
      const antigravityEnabled = (() => {
        try { return !!cfg.get('mcpAntigravityEnabled', false); } catch (_) { return false; }
      })();
      const cursorEnabled = (() => {
        try { return !!cfg.get('mcpCursorEnabled', false); } catch (_) { return false; }
      })();
      const windsurfMcpPath = (() => {
        try {
          const custom = (cfg.get('windsurfMcpPath') || '').trim();
          return custom || getDefaultWindsurfMcpPath();
        } catch (_) {
          return getDefaultWindsurfMcpPath();
        }
      })();
      const augmentMcpPath = (() => {
        try {
          const custom = (cfg.get('augmentMcpPath') || '').trim();
          return custom || getDefaultAugmentMcpPath();
        } catch (_) {
          return getDefaultAugmentMcpPath();
        }
      })();
      const antigravityMcpPath = (() => {
        try {
          const custom = (cfg.get('antigravityMcpPath') || '').trim();
          return custom || getDefaultAntigravityMcpPath();
        } catch (_) {
          return getDefaultAntigravityMcpPath();
        }
      })();
      const cursorMcpPath = (() => {
        try {
          const custom = (cfg.get('cursorMcpPath') || '').trim();
          return custom || getDefaultCursorMcpPath();
        } catch (_) {
          return getDefaultCursorMcpPath();
        }
      })();

      const bridgeMode = (() => {
        const mode = resolveMcpMode(cfg);
        return typeof mode === 'string' && mode.startsWith('bridge/');
      })();

      const authEnabled = bridgeMode && endpoint && endpointReachable !== false ? await getCachedAuthEnabled(endpoint) : undefined;
      const showAuth = !!(bridgeMode && endpoint && endpointReachable !== false && (authEnabled === true || authEnabled === undefined));

      const missingEndpoint = !endpointExplicitlyConfigured || !endpoint;
      const missingTarget = !targetPath || !targetExists;
      const missingClaudeMcpConfig = !!(claudeEnabled && !mcpConfigPath);
      const missingWindsurfMcpConfig = !!(windsurfEnabled && windsurfMcpPath && !pathExists(windsurfMcpPath));
      const missingAugmentMcpConfig = !!(augmentEnabled && augmentMcpPath && !pathExists(augmentMcpPath));
      const missingAntigravityMcpConfig = !!(antigravityEnabled && antigravityMcpPath && !pathExists(antigravityMcpPath));
      const missingCursorMcpConfig = !!(cursorEnabled && cursorMcpPath && !pathExists(cursorMcpPath));
      const missingAnyMcpConfig = !!(missingClaudeMcpConfig || missingWindsurfMcpConfig || missingAugmentMcpConfig || missingAntigravityMcpConfig || missingCursorMcpConfig);
      const missingCtxConfig = !ctxConfigPath;

      // Onboarding mode state
      const onboardingMode = (() => {
        try { return cfg.get('onboardingMode') || ''; } catch (_) { return ''; }
      })();
      const setupComplete = (() => {
        try { return !!cfg.get('setupComplete', false); } catch (_) { return false; }
      })();

      const items = [];

      // Show mode indicator if mode is selected
      if (onboardingMode) {
        const isLocal = onboardingMode === 'local';
        const modeLabel = isLocal ? 'Local Mode (Docker)' : 'Remote Server';
        const modeIcon = isLocal ? 'server-environment' : 'cloud-upload';
        const modeDescription = setupComplete ? 'Ready' : 'Setting up...';
        items.push(makeTreeItem(modeLabel, {
          description: modeDescription,
          icon: new vscode.ThemeIcon(modeIcon),
          tooltip: isLocal
            ? 'Using local Docker stack at localhost:8004'
            : `Using remote endpoint: ${endpoint || '(not configured)'}`,
        }));
      }

      items.push(
        makeTreeItem('Setup Workspace', {
          icon: new vscode.ThemeIcon('rocket'),
          command: { command: 'contextEngineUploader.setupWorkspace', title: 'Setup Workspace' },
          tooltip: 'Create and configure a profile for this workspace (recommended for first-time setup).',
        }),
      );

      const showCloneStack = !!(
        onboarding &&
        typeof onboarding.cloneAndStartStack === 'function' &&
        (
          endpointReachable === false ||
          (!endpointExplicitlyConfigured && endpointReachable !== true)
        )
      );

      if (showCloneStack) {
        items.push(makeTreeItem('Clone & Start Context Engine Stack', {
          icon: new vscode.ThemeIcon('cloud-download'),
          command: { command: 'contextEngineUploader.cloneAndStartStack', title: 'Clone Stack & Run docker compose' },
          tooltip: 'Clone https://github.com/m1rl0k/Context-Engine.git into a folder you choose and run docker compose up -d.',
        }));
      }

      const savedStackPath = (() => {
        try {
          if (onboarding && typeof onboarding.getSavedStackPath === 'function') {
            return onboarding.getSavedStackPath();
          }
        } catch (_) {
        }
        return undefined;
      })();

      if (endpointReachable === false && savedStackPath) {
        items.push(makeTreeItem('Start Context Engine Stack', {
          icon: new vscode.ThemeIcon('play'),
          command: { command: 'contextEngineUploader.startSavedStack', title: 'Start Saved Stack' },
          tooltip: `Start docker compose for the previously cloned stack at ${savedStackPath}`,
        }));
      }

      items.push(
        makeTreeItem('Read Docs', {
          icon: new vscode.ThemeIcon('book'),
          command: {
            command: 'vscode.open',
            title: 'Open Context Engine Docs',
            arguments: [vscode.Uri.parse('https://github.com/m1rl0k/Context-Engine/blob/test/docs/GETTING_STARTED.md')],
          },
          tooltip: 'Open the Context Engine documentation in your browser.',
        })
      );

      items.push(
        makeTreeItem('Open Settings', {
          icon: new vscode.ThemeIcon('gear'),
          command: { command: 'workbench.action.openSettings', title: 'Open Settings', arguments: ['contextEngineUploader'] },
          tooltip: 'Open VS Code settings filtered to Context Engine Uploader.',
        })
      );

      if (missingEndpoint) {
        items.push(makeTreeItem('Check Endpoint', {
          description: '(unset)',
          icon: new vscode.ThemeIcon('warning'),
          command: { command: 'workbench.action.openSettings', title: 'Open Settings', arguments: ['contextEngineUploader.endpoint'] },
          tooltip: 'Configure the upload service endpoint.',
        }));
      }

      if (missingTarget) {
        items.push(makeTreeItem('Check Target Path', {
          description: targetPath ? `${targetDescription} (missing)` : '(unset)',
          icon: new vscode.ThemeIcon('warning'),
          command: { command: 'workbench.action.openSettings', title: 'Open Settings', arguments: ['contextEngineUploader.targetPath'] },
          tooltip: 'Configure the target path to index/upload.',
        }));
      }

      if (missingAnyMcpConfig) {
        items.push(makeTreeItem('Write MCP Config...', {
          description: 'Missing',
          icon: new vscode.ThemeIcon('warning'),
          command: { command: 'contextEngineUploader.writeMcpConfigSelect', title: 'Write MCP Config...' },
          tooltip: 'Select which MCP config to write (All enabled, Claude, Windsurf, Augment, Antigravity, Cursor).',
        }));
      }

      if (missingCtxConfig) {
        items.push(makeTreeItem('Write CTX Config (ctx_config.json)', {
          description: 'Missing',
          icon: new vscode.ThemeIcon('warning'),
          command: { command: 'contextEngineUploader.writeCtxConfig', title: 'Write CTX Config' },
          tooltip: 'Scaffold ctx_config.json/.env for local tools (Prompt+, etc.).',
        }));
      }

      if (!missingEndpoint && !missingTarget && !missingAnyMcpConfig && !missingCtxConfig) {
        items.push(makeTreeItem('All set', {
          description: 'Ready',
          icon: new vscode.ThemeIcon('check'),
          tooltip: 'Workspace looks ready. You can start indexing/uploading now.',
        }));
      }

      if (showAuth) {
        const authDeps = {
          resolveBridgeCliInvocation,
          getWorkspaceFolderPath,
          spawn,
          log,
        };
        items.push(await buildAuthMenuItem(endpoint, authDeps));
      }

      return items;
    }

    if (element.contextValue === 'ctxceActionsUploadRoot') {
      return [
        makeTreeItem('Force Index Now', {
          icon: new vscode.ThemeIcon('sync'),
          command: { command: 'contextEngineUploader.indexCodebase', title: 'Index Codebase' },
          tooltip: 'Runs the force upload once (then watch if enabled).',
        }),
        makeTreeItem('Start Upload / Watch', {
          icon: new vscode.ThemeIcon('play'),
          command: { command: 'contextEngineUploader.start', title: 'Start Upload / Watch' },
        }),
        makeTreeItem('Stop Upload / Watch', {
          icon: new vscode.ThemeIcon('stop'),
          command: { command: 'contextEngineUploader.stop', title: 'Stop Upload / Watch' },
        }),
        makeTreeItem('Restart Upload / Watch', {
          icon: new vscode.ThemeIcon('refresh'),
          command: { command: 'contextEngineUploader.restart', title: 'Restart Upload / Watch' },
        }),
        makeTreeItem('Show Extension Output', {
          icon: new vscode.ThemeIcon('output'),
          command: { command: 'contextEngineUploader.showUploadServiceLogs', title: 'Show Extension Output' },
        }),
        makeTreeItem('Tail Upload Service Logs (Docker)', {
          icon: new vscode.ThemeIcon('terminal'),
          command: { command: 'contextEngineUploader.tailUploadServiceLogs', title: 'Tail Upload Service Logs (Docker)' },
        }),
      ];
    }

    if (element.contextValue === 'ctxceActionsBridgeRoot') {
      return [
        makeTreeItem('Write MCP Config...', {
          icon: new vscode.ThemeIcon('file-code'),
          command: { command: 'contextEngineUploader.writeMcpConfigSelect', title: 'Write MCP Config...' },
          tooltip: 'Select which MCP config to write (All enabled, Claude, Windsurf, Augment, Antigravity, Cursor).',
        }),
        makeTreeItem('Write CTX Config (ctx_config.json)', {
          icon: new vscode.ThemeIcon('file-text'),
          command: { command: 'contextEngineUploader.writeCtxConfig', title: 'Write CTX Config' },
        }),
        makeTreeItem('Start MCP HTTP Bridge', {
          icon: new vscode.ThemeIcon('broadcast'),
          command: { command: 'contextEngineUploader.startMcpHttpBridge', title: 'Start MCP HTTP Bridge' },
        }),
        makeTreeItem('Stop MCP HTTP Bridge', {
          icon: new vscode.ThemeIcon('debug-stop'),
          command: { command: 'contextEngineUploader.stopMcpHttpBridge', title: 'Stop MCP HTTP Bridge' },
        }),
      ];
    }

    if (element.contextValue === 'ctxceActionsUtilitiesRoot') {
      const cfg = getEffectiveConfig ? getEffectiveConfig() : vscode.workspace.getConfiguration('contextEngineUploader');
      const endpoint = (() => {
        try { return (cfg.get('endpoint') || '').trim(); } catch (_) { return ''; }
      })();
      const bridgeMode = (() => {
        const mode = resolveMcpMode(cfg);
        return typeof mode === 'string' && mode.startsWith('bridge/');
      })();
      const endpointReachable = endpoint ? await getCachedEndpointReachable(endpoint) : undefined;
      const authEnabled = bridgeMode && endpoint && endpointReachable !== false ? await getCachedAuthEnabled(endpoint) : undefined;
      const showAuth = !!(bridgeMode && endpoint && endpointReachable !== false && (authEnabled === true || authEnabled === undefined));

      const items = [
        makeTreeItem('Prompt+ (Replace Selection)', { icon: new vscode.ThemeIcon('sparkle'), command: { command: 'contextEngineUploader.promptEnhance', title: 'Prompt+ (Replace Selection)' } }),
        makeTreeItem('Prompt+ (Copy to Clipboard)', { icon: new vscode.ThemeIcon('copy'), command: { command: 'contextEngineUploader.promptEnhanceCopy', title: 'Prompt+ (Copy to Clipboard)' } }),
        makeTreeItem('Prompt+ (Open in New Editor)', { icon: new vscode.ThemeIcon('open-preview'), command: { command: 'contextEngineUploader.promptEnhanceOpen', title: 'Prompt+ (Open in New Editor)' } }),
        makeTreeItem('Prompt+ Default Mode...', { icon: new vscode.ThemeIcon('settings-gear'), command: { command: 'contextEngineUploader.setCtxDefaultMode', title: 'Prompt+ Default Mode' } }),
      ];

      if (showAuth) {
        const authDeps = {
          resolveBridgeCliInvocation,
          getWorkspaceFolderPath,
          spawn,
          log,
        };
        items.push(await buildAuthMenuItem(endpoint, authDeps));
      }

      return items;
    }

    return [];
  });

  providers.push(profilesProvider, statusProvider, actionsProvider);

  const setActiveDisposable = vscode.commands.registerCommand('contextEngineUploader._setActiveProfile', async (profileId) => {
    if (!profiles || typeof profiles.setActiveProfileId !== 'function') {
      return;
    }
    await profiles.setActiveProfileId(profileId || undefined);
    profilesProvider.refresh();
    statusProvider.refresh();
  });

  context.subscriptions.push(setActiveDisposable);

  const profilesTree = vscode.window.createTreeView('contextEngineUploaderProfiles', { treeDataProvider: profilesProvider, showCollapseAll: false });
  const statusTree = vscode.window.createTreeView('contextEngineUploaderStatus', { treeDataProvider: statusProvider, showCollapseAll: false });
  const actionsTree = vscode.window.createTreeView('contextEngineUploaderActions', { treeDataProvider: actionsProvider, showCollapseAll: false });

  context.subscriptions.push(profilesTree, statusTree, actionsTree);

  let refreshTimer;
  const bumpTimer = () => {
    const visible = profilesTree.visible || statusTree.visible || actionsTree.visible;
    if (!visible) {
      if (refreshTimer) {
        clearInterval(refreshTimer);
        refreshTimer = undefined;
      }
      return;
    }
    if (!refreshTimer) {
      refreshTimer = setInterval(() => {
        profilesProvider.refresh();
        statusProvider.refresh();
        actionsProvider.refresh();
        pruneCache(_authStatusCache, _AUTH_STATUS_TTL_MS, _AUTH_STATUS_MAX_ENTRIES);
        pruneCache(_endpointReachableCache, _ENDPOINT_REACHABLE_TTL_MS, _ENDPOINT_REACHABLE_MAX_ENTRIES);
      }, 2000);
    }
  };

  profilesTree.onDidChangeVisibility(bumpTimer, null, context.subscriptions);
  statusTree.onDidChangeVisibility(bumpTimer, null, context.subscriptions);
  actionsTree.onDidChangeVisibility(bumpTimer, null, context.subscriptions);

  context.subscriptions.push({
    dispose: () => {
      if (refreshTimer) {
        clearInterval(refreshTimer);
        refreshTimer = undefined;
      }
    }
  });

  bumpTimer();

  return {
    refresh: () => {
      for (const p of providers) {
        p.refresh();
      }
    },
  };
}

module.exports = {
  register,
};
