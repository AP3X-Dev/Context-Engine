/**
 * Dashboard Webview Provider for Context-Engine.AI
 * Creates a rich webview panel similar to Augment's Project Home dashboard
 */
const vscode = require('vscode');

class DashboardViewProvider {
  static viewType = 'contextEngineDashboard';

  constructor(extensionUri, deps) {
    this._extensionUri = extensionUri;
    this._view = undefined;
    this._deps = deps || {};
  }

  resolveWebviewView(webviewView, context, _token) {
    this._view = webviewView;

    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this._extensionUri],
    };

    webviewView.webview.html = this._getHtmlContent(webviewView.webview);

    // Handle messages from webview
    webviewView.webview.onDidReceiveMessage(async (message) => {
      switch (message.command) {
        case 'openSettings':
          vscode.commands.executeCommand('workbench.action.openSettings', 'contextEngineUploader');
          break;
        case 'startIndexing':
          vscode.commands.executeCommand('contextEngineUploader.start');
          break;
        case 'stopIndexing':
          vscode.commands.executeCommand('contextEngineUploader.stop');
          break;
        case 'writeMcpConfig':
          vscode.commands.executeCommand('contextEngineUploader.writeMcpConfigSelect');
          break;
        case 'setupWorkspace':
          vscode.commands.executeCommand('contextEngineUploader.setupWorkspace');
          break;
        case 'toggleIntegration':
          this._toggleIntegration(message.integration, message.enabled);
          break;
        case 'openDocs':
          vscode.env.openExternal(vscode.Uri.parse('https://github.com/m1rl0k/Context-Engine/blob/test/docs/GETTING_STARTED.md'));
          break;
        case 'refreshDashboard':
          this.refresh();
          break;
        case 'cloneStack':
          vscode.commands.executeCommand('contextEngineUploader.cloneAndStartStack');
          break;
        case 'dismissSetup':
          vscode.workspace.getConfiguration('contextEngineUploader').update('setupDismissed', true, vscode.ConfigurationTarget.Global);
          this.refresh();
          break;
      }
    });
  }

  async _toggleIntegration(integration, enabled) {
    const configKey = `mcp${integration.charAt(0).toUpperCase() + integration.slice(1)}Enabled`;
    await vscode.workspace.getConfiguration('contextEngineUploader').update(configKey, enabled, vscode.ConfigurationTarget.Global);
    this.refresh();
  }

  refresh() {
    if (this._view) {
      this._view.webview.html = this._getHtmlContent(this._view.webview);
    }
  }

  _getState() {
    const cfg = vscode.workspace.getConfiguration('contextEngineUploader');
    const getState = this._deps.getState;
    const state = typeof getState === 'function' ? getState() : {};
    
    return {
      endpoint: cfg.get('endpoint') || 'http://localhost:8004',
      targetPath: cfg.get('targetPath') || '',
      statusMode: state.statusMode || 'idle',
      bridgeRunning: !!(state.httpBridgeProcess),
      bridgePort: state.httpBridgePort || cfg.get('mcpBridgePort') || 30810,
      claudeEnabled: cfg.get('mcpClaudeEnabled', true),
      windsurfEnabled: cfg.get('mcpWindsurfEnabled', false),
      augmentEnabled: cfg.get('mcpAugmentEnabled', false),
      antigravityEnabled: cfg.get('mcpAntigravityEnabled', false),
      setupDismissed: cfg.get('setupDismissed', false),
    };
  }

  _getHtmlContent(webview) {
    const state = this._getState();
    const nonce = getNonce();
    const logoUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'assets', 'logo.jpeg'));
    
    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; font-src https://microsoft.github.io; img-src ${webview.cspSource}; script-src 'nonce-${nonce}';">
  <title>Context Engine Dashboard</title>
  <link href="https://microsoft.github.io/vscode-codicons/dist/codicon.css" rel="stylesheet">
  <style>
    ${this._getStyles()}
  </style>
</head>
<body>
  <div class="dashboard">
    ${this._getHeaderHtml(state, logoUri)}
    ${this._getSetupCardHtml(state)}
    ${this._getQuickActionsHtml(state)}
    ${this._getIntegrationsHtml(state)}
    ${this._getStatusHtml(state)}
  </div>
  <script nonce="${nonce}">
    ${this._getScript()}
  </script>
</body>
</html>`;
  }

  _getStyles() {
    return `
    :root {
      /* Theme-aware color system */
      --bg-primary: var(--vscode-editor-background);
      --bg-secondary: var(--vscode-sideBar-background);
      --bg-card: var(--vscode-editorWidget-background);
      --bg-elevated: var(--vscode-dropdown-background, var(--bg-card));
      --text-primary: var(--vscode-foreground);
      --text-secondary: var(--vscode-descriptionForeground);
      --text-muted: color-mix(in srgb, var(--text-secondary) 70%, transparent);
      --accent: var(--vscode-button-background);
      --accent-hover: var(--vscode-button-hoverBackground);
      --accent-subtle: color-mix(in srgb, var(--accent) 15%, transparent);
      --border: var(--vscode-panel-border);
      --border-subtle: color-mix(in srgb, var(--border) 50%, transparent);

      /* Semantic colors */
      --success: #30a46c;
      --success-subtle: color-mix(in srgb, #30a46c 15%, transparent);
      --warning: #ffc53d;
      --warning-subtle: color-mix(in srgb, #ffc53d 15%, transparent);
      --error: #e5484d;
      --error-subtle: color-mix(in srgb, #e5484d 15%, transparent);

      /* Spacing scale */
      --space-1: 4px;
      --space-2: 8px;
      --space-3: 12px;
      --space-4: 16px;
      --space-5: 24px;

      /* Typography */
      --font-size-xs: 11px;
      --font-size-sm: 12px;
      --font-size-base: 13px;
      --font-size-lg: 14px;

      /* Radii */
      --radius-sm: 4px;
      --radius-md: 6px;
      --radius-lg: 8px;
      --radius-full: 9999px;

      /* Shadows */
      --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.05);
      --shadow-md: 0 2px 8px rgba(0, 0, 0, 0.08);
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: var(--vscode-font-family);
      font-size: var(--font-size-base);
      color: var(--text-primary);
      background: var(--bg-primary);
      padding: var(--space-4);
      line-height: 1.5;
      -webkit-font-smoothing: antialiased;
    }

    .dashboard {
      max-width: 100%;
      animation: fadeIn 0.2s ease-out;
    }

    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(4px); }
      to { opacity: 1; transform: translateY(0); }
    }

    /* Header */
    .header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: var(--space-4);
      padding-bottom: var(--space-3);
      border-bottom: 1px solid var(--border-subtle);
    }

    .header h1 {
      font-size: var(--font-size-lg);
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: var(--space-2);
      letter-spacing: -0.01em;
    }

    .header .logo-img {
      width: 18px;
      height: 18px;
      border-radius: var(--radius-sm);
      object-fit: cover;
    }

    .header .stats {
      display: flex;
      gap: var(--space-3);
      font-size: var(--font-size-xs);
      color: var(--text-secondary);
    }

    .status-badge {
      display: inline-flex;
      align-items: center;
      gap: var(--space-1);
      padding: 2px 8px;
      border-radius: var(--radius-full);
      font-size: var(--font-size-xs);
      font-weight: 500;
    }

    .status-badge.idle { background: var(--bg-secondary); color: var(--text-secondary); }
    .status-badge.active { background: var(--success-subtle); color: var(--success); }
    .status-badge::before {
      content: '';
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: currentColor;
    }
    .status-badge.active::before {
      animation: pulse 2s ease-in-out infinite;
    }

    @keyframes pulse {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.4; }
    }

    /* Cards */
    .card {
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-lg);
      padding: var(--space-3);
      margin-bottom: var(--space-3);
      transition: border-color 0.15s ease;
    }

    .card:hover {
      border-color: var(--border);
    }

    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: var(--space-2);
    }

    .card-title {
      font-size: var(--font-size-sm);
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: var(--space-2);
      color: var(--text-primary);
    }

    .card-title .codicon {
      opacity: 0.7;
    }

    .card-dismiss {
      background: none;
      border: none;
      color: var(--text-muted);
      cursor: pointer;
      font-size: 14px;
      padding: var(--space-1);
      border-radius: var(--radius-sm);
      transition: all 0.15s ease;
      display: flex;
      align-items: center;
      justify-content: center;
    }

    .card-dismiss:hover {
      color: var(--text-primary);
      background: var(--bg-secondary);
    }

    /* Buttons */
    .btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      padding: 7px 12px;
      border: none;
      border-radius: var(--radius-md);
      cursor: pointer;
      font-size: var(--font-size-sm);
      font-weight: 500;
      font-family: inherit;
      transition: all 0.15s ease;
      text-decoration: none;
    }

    .btn:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }

    .btn-primary {
      background: var(--accent);
      color: var(--vscode-button-foreground, #fff);
      box-shadow: var(--shadow-sm);
    }

    .btn-primary:hover:not(:disabled) {
      background: var(--accent-hover);
      transform: translateY(-1px);
      box-shadow: var(--shadow-md);
    }

    .btn-primary:active:not(:disabled) {
      transform: translateY(0);
    }

    .btn-secondary {
      background: var(--bg-elevated);
      color: var(--text-primary);
      border: 1px solid var(--border-subtle);
    }

    .btn-secondary:hover:not(:disabled) {
      background: var(--bg-secondary);
      border-color: var(--border);
    }

    .btn .codicon {
      font-size: 14px;
    }

    /* Actions Grid */
    .actions-grid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: var(--space-2);
    }

    /* Integrations */
    .integration-list {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }

    .integration-item {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: var(--space-2) var(--space-3);
      background: var(--bg-secondary);
      border-radius: var(--radius-md);
      transition: background 0.15s ease;
    }

    .integration-item:hover {
      background: color-mix(in srgb, var(--bg-secondary) 80%, var(--accent) 5%);
    }

    .integration-name {
      display: flex;
      align-items: center;
      gap: var(--space-2);
      font-size: var(--font-size-sm);
      font-weight: 500;
    }

    .integration-name .codicon {
      font-size: 14px;
      opacity: 0.8;
    }

    /* Toggle Switch */
    .toggle {
      position: relative;
      width: 36px;
      height: 20px;
      flex-shrink: 0;
    }

    .toggle input {
      opacity: 0;
      width: 0;
      height: 0;
      position: absolute;
    }

    .toggle-slider {
      position: absolute;
      cursor: pointer;
      inset: 0;
      background: var(--border);
      border-radius: var(--radius-full);
      transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
    }

    .toggle-slider::before {
      content: '';
      position: absolute;
      height: 14px;
      width: 14px;
      left: 3px;
      bottom: 3px;
      background: var(--bg-elevated);
      border-radius: 50%;
      transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
    }

    .toggle input:checked + .toggle-slider {
      background: var(--success);
    }

    .toggle input:checked + .toggle-slider::before {
      transform: translateX(16px);
      background: #fff;
    }

    .toggle input:focus-visible + .toggle-slider {
      outline: 2px solid var(--accent);
      outline-offset: 2px;
    }

    /* Status Grid */
    .status-grid {
      display: flex;
      flex-direction: column;
      gap: 2px;
    }

    .status-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: var(--font-size-sm);
      padding: 6px 0;
      border-bottom: 1px solid var(--border-subtle);
    }

    .status-row:last-child {
      border-bottom: none;
    }

    .status-label {
      color: var(--text-secondary);
      font-weight: 400;
    }

    .status-value {
      font-weight: 500;
      font-family: var(--vscode-editor-font-family, monospace);
      font-size: var(--font-size-xs);
    }

    .status-value.success { color: var(--success); }
    .status-value.warning { color: var(--warning); }
    .status-value.error { color: var(--error); }

    /* Setup card special styling */
    .card.setup-card {
      background: linear-gradient(135deg,
        color-mix(in srgb, var(--accent) 8%, var(--bg-card)),
        var(--bg-card)
      );
      border-color: color-mix(in srgb, var(--accent) 20%, var(--border-subtle));
    }

    .setup-description {
      font-size: var(--font-size-sm);
      color: var(--text-secondary);
      margin-bottom: var(--space-3);
      line-height: 1.6;
    }

    .setup-actions {
      display: flex;
      gap: var(--space-2);
      flex-wrap: wrap;
    }
  `;
  }

  _getHeaderHtml(state, logoUri) {
    const isActive = state.statusMode === 'indexing' || state.statusMode === 'watching';
    const statusText = state.statusMode === 'indexing' ? 'Indexing' : state.statusMode === 'watching' ? 'Watching' : 'Idle';
    const statusClass = isActive ? 'active' : 'idle';
    return `
    <div class="header">
      <h1>
        <img src="${logoUri}" alt="Context Engine" class="logo-img">
        Context Engine
      </h1>
      <div class="stats">
        <span class="status-badge ${statusClass}">${statusText}</span>
      </div>
    </div>`;
  }

  _getSetupCardHtml(state) {
    if (state.setupDismissed) return '';
    return `
    <div class="card setup-card">
      <div class="card-header">
        <span class="card-title"><i class="codicon codicon-rocket"></i> Get Started</span>
        <button class="card-dismiss" onclick="dismissSetup()"><i class="codicon codicon-close"></i></button>
      </div>
      <p class="setup-description">
        Index your codebase to give AI assistants deep understanding of your code structure, patterns, and conventions.
      </p>
      <div class="setup-actions">
        <button class="btn btn-primary" onclick="setupWorkspace()"><i class="codicon codicon-wand"></i> Setup Workspace</button>
        <button class="btn btn-secondary" onclick="openDocs()"><i class="codicon codicon-book"></i> Documentation</button>
      </div>
    </div>`;
  }

  _getQuickActionsHtml(state) {
    const isRunning = state.statusMode === 'indexing' || state.statusMode === 'watching';
    return `
    <div class="card">
      <div class="card-title" style="margin-bottom:var(--space-3);"><i class="codicon codicon-zap"></i> Quick Actions</div>
      <div class="actions-grid">
        <button class="btn btn-primary" onclick="startIndexing()" ${isRunning ? 'disabled' : ''}><i class="codicon codicon-play"></i> Start</button>
        <button class="btn btn-secondary" onclick="stopIndexing()" ${!isRunning ? 'disabled' : ''}><i class="codicon codicon-debug-stop"></i> Stop</button>
        <button class="btn btn-secondary" onclick="writeMcpConfig()"><i class="codicon codicon-json"></i> MCP Config</button>
        <button class="btn btn-secondary" onclick="openSettings()"><i class="codicon codicon-settings-gear"></i> Settings</button>
      </div>
    </div>`;
  }

  _getIntegrationsHtml(state) {
    const integrations = [
      { id: 'claude', name: 'Claude Code', enabled: state.claudeEnabled, icon: 'comment-discussion' },
      { id: 'windsurf', name: 'Windsurf', enabled: state.windsurfEnabled, icon: 'symbol-event' },
      { id: 'augment', name: 'Augment', enabled: state.augmentEnabled, icon: 'sparkle' },
      { id: 'antigravity', name: 'Antigravity', enabled: state.antigravityEnabled, icon: 'telescope' },
    ];

    return `
    <div class="card">
      <div class="card-title" style="margin-bottom:var(--space-3);"><i class="codicon codicon-plug"></i> MCP Integrations</div>
      <div class="integration-list">
        ${integrations.map(i => `
          <div class="integration-item">
            <span class="integration-name"><i class="codicon codicon-${i.icon}"></i> ${i.name}</span>
            <label class="toggle">
              <input type="checkbox" ${i.enabled ? 'checked' : ''} onchange="toggleIntegration('${i.id}', this.checked)">
              <span class="toggle-slider"></span>
            </label>
          </div>
        `).join('')}
      </div>
    </div>`;
  }

  _getStatusHtml(state) {
    const bridgeStatus = state.bridgeRunning ? `Running :${state.bridgePort}` : 'Stopped';
    const bridgeClass = state.bridgeRunning ? 'success' : '';
    const shortEndpoint = state.endpoint.replace(/^https?:\/\//, '');
    const shortPath = state.targetPath ? (state.targetPath.length > 30 ? '...' + state.targetPath.slice(-27) : state.targetPath) : 'Current workspace';

    return `
    <div class="card">
      <div class="card-title" style="margin-bottom:var(--space-3);"><i class="codicon codicon-pulse"></i> Status</div>
      <div class="status-grid">
        <div class="status-row">
          <span class="status-label">Server</span>
          <span class="status-value">${shortEndpoint}</span>
        </div>
        <div class="status-row">
          <span class="status-label">Path</span>
          <span class="status-value" title="${state.targetPath || ''}">${shortPath}</span>
        </div>
        <div class="status-row">
          <span class="status-label">MCP Bridge</span>
          <span class="status-value ${bridgeClass}">${bridgeStatus}</span>
        </div>
      </div>
    </div>`;
  }

  _getScript() {
    return `
    const vscode = acquireVsCodeApi();
    function send(cmd, data) { vscode.postMessage({ command: cmd, ...data }); }
    function openSettings() { send('openSettings'); }
    function startIndexing() { send('startIndexing'); }
    function stopIndexing() { send('stopIndexing'); }
    function writeMcpConfig() { send('writeMcpConfig'); }
    function setupWorkspace() { send('setupWorkspace'); }
    function openDocs() { send('openDocs'); }
    function dismissSetup() { send('dismissSetup'); }
    function toggleIntegration(id, enabled) { send('toggleIntegration', { integration: id, enabled }); }
    `;
  }
}

function getNonce() {
  let text = '';
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  for (let i = 0; i < 32; i++) {
    text += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return text;
}

function createDashboardViewProvider(extensionUri, deps) {
  return new DashboardViewProvider(extensionUri, deps);
}

module.exports = { DashboardViewProvider, createDashboardViewProvider };

