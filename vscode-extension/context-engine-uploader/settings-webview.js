/**
 * Settings Webview for Context-Engine.AI
 * A beautiful HTML-based settings UI similar to Augment's approach
 */
const vscode = require('vscode');

// Settings grouped by category
const SETTINGS_SCHEMA = {
  status: {
    title: 'Status',
    icon: 'pulse',
    description: 'Live indexing progress and system status',
    isStatus: true,  // Special flag for status section rendering
    settings: []  // No editable settings - purely informational
  },
  general: {
    title: 'General',
    icon: 'home',
    description: 'Core configuration for Context Engine',
    settings: [
      { key: 'runOnStartup', label: 'Run on Startup', type: 'boolean', description: 'Automatically start indexing when VS Code opens' },
      { key: 'endpoint', label: 'Server Endpoint', type: 'string', description: 'URL for the upload server', placeholder: 'http://localhost:8004' },
      { key: 'targetPath', label: 'Workspace Path', type: 'string', description: 'Path to index (leave empty for current workspace)', placeholder: '/path/to/project' },
      { key: 'pythonPath', label: 'Python Path', type: 'string', description: 'Python executable for scripts', placeholder: 'python3' },
    ]
  },
  team: {
    title: 'Team',
    icon: 'organization',
    description: 'Shared authentication for team deployments',
    settings: [
      { key: 'authBackendUrl', label: 'Auth Backend URL', type: 'string', description: 'Upload service URL for authentication (e.g. http://ce.yourteam.com/upload)', placeholder: 'http://localhost:8004' },
      { key: 'authSharedToken', label: 'Shared API Token', type: 'password', description: 'Team-wide shared token for upload authentication. All team members use the same token.', placeholder: '••••••••' },
    ]
  },
  indexing: {
    title: 'Indexing',
    icon: 'database',
    description: 'Watch mode and git history settings',
    settings: [
      { key: 'intervalSeconds', label: 'Watch Interval', type: 'number', description: 'Seconds between watch mode polls', min: 1 },
      { key: 'startWatchAfterForce', label: 'Auto-start Watch', type: 'boolean', description: 'Start watch mode after force sync' },
      { key: 'gitMaxCommits', label: 'Git Max Commits', type: 'number', description: 'Maximum git commits to index (0 to disable)', min: 0 },
      { key: 'gitSince', label: 'Git Since', type: 'string', description: 'Only index commits after this date', placeholder: '2 years ago' },
    ]
  },
  mcp: {
    title: 'MCP Integrations',
    icon: 'plug',
    description: 'Enable MCP config writing for AI assistants',
    settings: [
      { key: 'mcpClaudeEnabled', label: 'Claude Code', type: 'boolean', description: 'Write .mcp.json for Claude Code' },
      { key: 'mcpWindsurfEnabled', label: 'Windsurf', type: 'boolean', description: 'Write MCP config for Windsurf/Codeium' },
      { key: 'mcpAugmentEnabled', label: 'Augment Code', type: 'boolean', description: 'Write MCP config for Augment' },
      { key: 'mcpAntigravityEnabled', label: 'Antigravity', type: 'boolean', description: 'Write MCP config for Google Antigravity' },
      { key: 'mcpCursorEnabled', label: 'Cursor', type: 'boolean', description: 'Write MCP config for Cursor (~/.cursor/mcp.json)' },
      { key: 'autoWriteMcpConfigOnStartup', label: 'Auto-write on Startup', type: 'boolean', description: 'Automatically write MCP configs when extension activates' },
    ]
  },
  mcpServer: {
    title: 'MCP Server',
    icon: 'server',
    description: 'Server architecture and bridge settings',
    settings: [
      { key: 'mcpServerMode', label: 'Server Mode', type: 'enum', options: ['bridge', 'direct'], description: 'Single bridge or separate indexer/memory servers' },
      { key: 'mcpTransportMode', label: 'Transport', type: 'enum', options: ['http', 'sse-remote'], description: 'HTTP direct or SSE tunnel transport' },
      { key: 'autoStartMcpBridge', label: 'Auto-start Bridge', type: 'boolean', description: 'Automatically start the MCP bridge server' },
      { key: 'mcpBridgePort', label: 'Bridge Port', type: 'number', description: 'Port for the MCP bridge HTTP server' },
      { key: 'mcpIndexerUrl', label: 'Indexer URL', type: 'string', description: 'MCP server URL for Qdrant indexer', placeholder: 'http://localhost:8003/mcp' },
      { key: 'mcpMemoryUrl', label: 'Memory URL', type: 'string', description: 'MCP server URL for memory/search', placeholder: 'http://localhost:8002/mcp' },
    ]
  },
  decoder: {
    title: 'Decoder & AI',
    icon: 'sparkle',
    description: 'Configure Prompt+ and AI backend',
    settings: [
      { key: 'decoderRuntime', label: 'Runtime', type: 'enum', options: ['glm', 'llamacpp'], description: 'GLM cloud API or local llama.cpp' },
      { key: 'decoderUrl', label: 'Decoder URL', type: 'string', description: 'Local llama.cpp endpoint', placeholder: 'http://localhost:8081' },
      { key: 'useGpuDecoder', label: 'Use GPU', type: 'boolean', description: 'Prefer GPU decoder for Prompt+' },
      { key: 'glmApiKey', label: 'GLM API Key', type: 'password', description: 'API key for GLM cloud service' },
      { key: 'glmApiBase', label: 'GLM API Base', type: 'string', description: 'GLM API base URL' },
      { key: 'glmModel', label: 'GLM Model', type: 'string', description: 'GLM model name', placeholder: 'glm-4.6' },
    ]
  },
  hook: {
    title: 'Claude Hook',
    icon: 'terminal',
    description: 'Claude Code prompt enhancement hook',
    settings: [
      { key: 'claudeHookEnabled', label: 'Enable Hook', type: 'boolean', description: 'Write Claude hook to .claude/settings.local.json' },
      { key: 'surfaceQdrantCollectionHint', label: 'Collection Hint', type: 'boolean', description: 'Add Qdrant collection ID hint to enhanced prompts' },
      { key: 'ctxIndexerUrl', label: 'CTX Indexer URL', type: 'string', description: 'MCP indexer endpoint for ctx.py', placeholder: 'http://localhost:8003/mcp' },
      { key: 'scaffoldCtxConfig', label: 'Scaffold Config', type: 'boolean', description: 'Create ctx_config.json and .env automatically' },
    ]
  },
  advanced: {
    title: 'Advanced',
    icon: 'settings-gear',
    description: 'Developer settings and overrides',
    settings: [
      { key: 'scriptWorkingDirectory', label: 'Script Directory', type: 'string', description: 'Override folder for upload scripts' },
      { key: 'hostRoot', label: 'Host Root', type: 'string', description: 'Host path prefix for container rewrites' },
      { key: 'containerRoot', label: 'Container Root', type: 'string', description: 'Container path mirroring host root', placeholder: '/work' },
      { key: 'devRemoteMode', label: 'Dev Remote Mode', type: 'boolean', description: 'Enable dev-remote upload mode' },
      { key: 'mcpBridgeBinPath', label: 'Bridge Binary', type: 'string', description: 'Path to ctxce CLI binary' },
      { key: 'mcpBridgeLocalOnly', label: 'Local Bridge Only', type: 'boolean', description: 'Prefer local bridge binaries' },
    ]
  },
  paths: {
    title: 'Custom Paths',
    icon: 'folder',
    description: 'Override default config file locations',
    settings: [
      { key: 'windsurfMcpPath', label: 'Windsurf Config', type: 'string', description: 'Custom Windsurf mcp_config.json path' },
      { key: 'augmentMcpPath', label: 'Augment Config', type: 'string', description: 'Custom Augment settings.json path' },
      { key: 'antigravityMcpPath', label: 'Antigravity Config', type: 'string', description: 'Custom Antigravity mcp_config.json path' },
    ]
  }
};

class SettingsWebviewProvider {
  static viewType = 'contextEngineSettingsPanel';

  constructor(extensionUri, getEndpoint) {
    this._extensionUri = extensionUri;
    this._getEndpoint = getEndpoint || (() => 'http://localhost:8004');
    this._panel = undefined;
    this._activeSection = 'status';  // Default to status section
  }

  openSettings() {
    const column = vscode.window.activeTextEditor
      ? vscode.window.activeTextEditor.viewColumn
      : undefined;

    if (this._panel) {
      this._panel.reveal(column);
      return;
    }

    this._panel = vscode.window.createWebviewPanel(
      SettingsWebviewProvider.viewType,
      'Context Engine Settings',
      column || vscode.ViewColumn.One,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [this._extensionUri],
      }
    );

    this._panel.webview.html = this._getHtmlContent(this._panel.webview);

    this._panel.onDidDispose(() => {
      this._panel = undefined;
    });

    this._panel.webview.onDidReceiveMessage(async (message) => {
      await this._handleMessage(message);
    });
  }

  async _handleMessage(message) {
    const cfg = vscode.workspace.getConfiguration('contextEngineUploader');
    switch (message.command) {
      case 'updateSetting':
        await cfg.update(message.key, message.value, vscode.ConfigurationTarget.Global);
        break;
      case 'setSection':
        this._activeSection = message.section;
        this.refresh();
        break;
      case 'openVsCodeSettings':
        vscode.commands.executeCommand('workbench.action.openSettings', 'contextEngineUploader');
        break;
    }
  }

  refresh() {
    if (this._panel) {
      this._panel.webview.html = this._getHtmlContent(this._panel.webview);
    }
  }

  _getAllSettings() {
    const cfg = vscode.workspace.getConfiguration('contextEngineUploader');
    const values = {};
    for (const [categoryKey, category] of Object.entries(SETTINGS_SCHEMA)) {
      for (const setting of category.settings) {
        values[setting.key] = cfg.get(setting.key);
      }
    }
    return values;
  }

  _getHtmlContent(webview) {
    const nonce = getNonce();
    const values = this._getAllSettings();
    const logoUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'assets', 'logo.jpeg'));
    const endpoint = this._getEndpoint();
    const workspacePath = values.targetPath || '';

    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; font-src https://microsoft.github.io; img-src ${webview.cspSource}; script-src 'nonce-${nonce}'; connect-src ${endpoint} http://localhost:8004 http://127.0.0.1:8004;">
  <title>Context Engine Settings</title>
  <link href="https://microsoft.github.io/vscode-codicons/dist/codicon.css" rel="stylesheet">
  <style>${this._getStyles()}</style>
</head>
<body>
  <div class="settings-container">
    <aside class="sidebar">
      <div class="sidebar-header">
        <img src="${logoUri}" alt="Context Engine" class="logo-img">
        <h1>Settings</h1>
      </div>
      <nav class="nav-list">
        ${this._getNavItems()}
      </nav>
      <div class="sidebar-footer">
        <button class="link-btn" onclick="openVsCodeSettings()">
          <span class="codicon codicon-json"></span>
          Edit JSON
        </button>
      </div>
    </aside>
    <main class="content">
      ${this._getSectionContent(values)}
    </main>
  </div>
  <script nonce="${nonce}">
    const STATUS_ENDPOINT = '${endpoint}';
    const WORKSPACE_PATH = '${workspacePath.replace(/\\/g, '\\\\').replace(/'/g, "\\'")}';
    ${this._getScript()}
  </script>
</body>
</html>`;
  }

  _getNavItems() {
    return Object.entries(SETTINGS_SCHEMA).map(([key, section]) => `
      <button class="nav-item ${this._activeSection === key ? 'active' : ''}" data-section="${key}">
        <span class="codicon codicon-${section.icon}"></span>
        <span>${section.title}</span>
      </button>
    `).join('');
  }

  _getSectionContent(values) {
    const section = SETTINGS_SCHEMA[this._activeSection];
    if (!section) return '';

    // Special rendering for status section
    if (section.isStatus) {
      return this._getStatusSectionHtml();
    }

    return `
      <div class="section-header">
        <h2><span class="codicon codicon-${section.icon}"></span> ${section.title}</h2>
        <p class="section-desc">${section.description}</p>
      </div>
      <div class="settings-list">
        ${section.settings.map(s => this._getSettingHtml(s, values[s.key])).join('')}
      </div>
    `;
  }

  _getStatusSectionHtml() {
    return `
      <div class="section-header">
        <h2><span class="codicon codicon-pulse"></span> Status</h2>
        <p class="section-desc">Live indexing progress and system status</p>
      </div>
      <div class="status-section">
        <div class="status-card" id="indexing-status-card">
          <div class="status-card-header">
            <span class="codicon codicon-database"></span>
            <span class="status-card-title">Indexing Status</span>
            <span class="status-badge" id="status-badge">Checking...</span>
          </div>
          <div class="status-card-body">
            <div class="progress-container" id="progress-container" style="display: none;">
              <div class="progress-info">
                <span id="progress-text">0 / 0 files</span>
                <span id="progress-percent">0%</span>
              </div>
              <div class="progress-bar">
                <div class="progress-fill" id="progress-fill" style="width: 0%"></div>
              </div>
              <div class="current-file" id="current-file"></div>
            </div>
            <div class="status-details" id="status-details">
              <div class="status-row">
                <span class="status-label">State</span>
                <span class="status-value" id="state-value">--</span>
              </div>
              <div class="status-row">
                <span class="status-label">Points Indexed</span>
                <span class="status-value" id="points-value">--</span>
              </div>
              <div class="status-row">
                <span class="status-label">Watcher</span>
                <span class="status-value" id="watcher-value">--</span>
              </div>
              <div class="status-row">
                <span class="status-label">Qdrant</span>
                <span class="status-value" id="qdrant-value">--</span>
              </div>
            </div>
          </div>
        </div>
        <div class="status-card" id="connection-status-card">
          <div class="status-card-header">
            <span class="codicon codicon-globe"></span>
            <span class="status-card-title">Server Connection</span>
            <span class="status-badge" id="connection-badge">Checking...</span>
          </div>
          <div class="status-card-body">
            <div class="status-row">
              <span class="status-label">Endpoint</span>
              <span class="status-value" id="endpoint-value">--</span>
            </div>
            <div class="status-row">
              <span class="status-label">Last Checked</span>
              <span class="status-value" id="last-checked-value">--</span>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  _getSettingHtml(setting, value) {
    const id = `setting-${setting.key}`;
    let input = '';

    switch (setting.type) {
      case 'boolean':
        input = `
          <label class="toggle">
            <input type="checkbox" id="${id}" ${value ? 'checked' : ''} onchange="updateSetting('${setting.key}', this.checked)">
            <span class="toggle-slider"></span>
          </label>`;
        break;
      case 'enum':
        input = `
          <select id="${id}" onchange="updateSetting('${setting.key}', this.value)">
            ${setting.options.map(opt => `<option value="${opt}" ${value === opt ? 'selected' : ''}>${opt}</option>`).join('')}
          </select>`;
        break;
      case 'number':
        input = `<input type="number" id="${id}" value="${value ?? ''}" ${setting.min !== undefined ? `min="${setting.min}"` : ''} onchange="updateSetting('${setting.key}', parseInt(this.value, 10))" placeholder="${setting.placeholder || ''}">`;
        break;
      case 'password':
        input = `<input type="password" id="${id}" value="${value || ''}" onchange="updateSetting('${setting.key}', this.value)" placeholder="••••••••">`;
        break;
      default:
        input = `<input type="text" id="${id}" value="${value || ''}" onchange="updateSetting('${setting.key}', this.value)" placeholder="${setting.placeholder || ''}">`;
    }

    return `
      <div class="setting-row">
        <div class="setting-info">
          <label for="${id}" class="setting-label">${setting.label}</label>
          <p class="setting-desc">${setting.description}</p>
        </div>
        <div class="setting-control">${input}</div>
      </div>`;
  }

  _getStyles() {
    return `
    :root {
      --bg-base: var(--vscode-editor-background);
      --bg-subtle: var(--vscode-sideBar-background);
      --bg-card: var(--vscode-editorWidget-background);
      --bg-hover: color-mix(in srgb, var(--vscode-list-hoverBackground) 80%, transparent);
      --text-primary: var(--vscode-foreground);
      --text-secondary: var(--vscode-descriptionForeground);
      --text-muted: color-mix(in srgb, var(--text-secondary) 60%, transparent);
      --accent: var(--vscode-button-background);
      --accent-hover: var(--vscode-button-hoverBackground);
      --border: var(--vscode-panel-border);
      --border-subtle: color-mix(in srgb, var(--border) 40%, transparent);
      --input-bg: var(--vscode-input-background);
      --input-border: var(--vscode-input-border);
      --focus-ring: var(--vscode-focusBorder);
      --radius-sm: 4px;
      --radius-md: 6px;
      --radius-lg: 8px;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: var(--vscode-font-family);
      font-size: 13px;
      color: var(--text-primary);
      background: var(--bg-base);
      line-height: 1.5;
      height: 100vh;
      overflow: hidden;
    }
    .settings-container {
      display: grid;
      grid-template-columns: 220px 1fr;
      height: 100vh;
    }
    .sidebar {
      background: var(--bg-subtle);
      border-right: 1px solid var(--border-subtle);
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }
    .sidebar-header {
      padding: 16px;
      display: flex;
      align-items: center;
      gap: 10px;
      border-bottom: 1px solid var(--border-subtle);
    }
    .sidebar-header .logo-img {
      width: 28px;
      height: 28px;
      border-radius: var(--radius-md);
      object-fit: cover;
    }
    .sidebar-header h1 {
      font-size: 14px;
      font-weight: 600;
    }
    .nav-list {
      flex: 1;
      overflow-y: auto;
      padding: 8px;
    }
    .nav-item {
      width: 100%;
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 10px 12px;
      background: transparent;
      border: none;
      border-radius: var(--radius-md);
      color: var(--text-secondary);
      cursor: pointer;
      font-size: 13px;
      text-align: left;
      transition: all 0.15s ease;
    }
    .nav-item:hover {
      background: var(--bg-hover);
      color: var(--text-primary);
    }
    .nav-item.active {
      background: color-mix(in srgb, var(--accent) 15%, transparent);
      color: var(--accent);
      font-weight: 500;
    }
    .nav-item .codicon { font-size: 16px; opacity: 0.8; }
    .sidebar-footer {
      padding: 12px;
      border-top: 1px solid var(--border-subtle);
    }
    .link-btn {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      background: transparent;
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-md);
      color: var(--text-secondary);
      cursor: pointer;
      font-size: 12px;
      width: 100%;
      transition: all 0.15s ease;
    }
    .link-btn:hover {
      background: var(--bg-hover);
      border-color: var(--border);
      color: var(--text-primary);
    }
    .content {
      overflow-y: auto;
      padding: 32px 40px;
    }
    .section-header { margin-bottom: 24px; }
    .section-header h2 {
      font-size: 18px;
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 8px;
    }
    .section-header h2 .codicon { color: var(--accent); }
    .section-desc { color: var(--text-secondary); font-size: 13px; }
    .settings-list { display: flex; flex-direction: column; gap: 2px; }
    .setting-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 16px;
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-md);
      margin-bottom: 8px;
      transition: border-color 0.15s ease;
    }
    .setting-row:hover { border-color: var(--border); }
    .setting-info { flex: 1; min-width: 0; padding-right: 24px; }
    .setting-label { font-weight: 500; display: block; margin-bottom: 4px; }
    .setting-desc { color: var(--text-secondary); font-size: 12px; }
    .setting-control { flex-shrink: 0; }
    input[type="text"], input[type="password"], input[type="number"], select {
      min-width: 200px;
      padding: 8px 12px;
      background: var(--input-bg);
      border: 1px solid var(--input-border);
      border-radius: var(--radius-sm);
      color: var(--text-primary);
      font-size: 13px;
      transition: border-color 0.15s ease;
    }
    input:focus, select:focus { outline: none; border-color: var(--focus-ring); }
    select { cursor: pointer; }
    .toggle { position: relative; display: inline-block; width: 40px; height: 22px; }
    .toggle input { opacity: 0; width: 0; height: 0; }
    .toggle-slider {
      position: absolute;
      cursor: pointer;
      inset: 0;
      background: var(--border);
      border-radius: 22px;
      transition: 0.2s ease;
    }
    .toggle-slider::before {
      content: '';
      position: absolute;
      width: 16px;
      height: 16px;
      left: 3px;
      bottom: 3px;
      background: white;
      border-radius: 50%;
      transition: 0.2s ease;
    }
    .toggle input:checked + .toggle-slider { background: var(--accent); }
    .toggle input:checked + .toggle-slider::before { transform: translateX(18px); }
    .toggle input:focus + .toggle-slider { box-shadow: 0 0 0 2px var(--focus-ring); }

    /* Status section styles */
    .status-section { display: flex; flex-direction: column; gap: 16px; }
    .status-card {
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-lg);
      overflow: hidden;
    }
    .status-card-header {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 14px 16px;
      background: var(--bg-subtle);
      border-bottom: 1px solid var(--border-subtle);
    }
    .status-card-header .codicon { font-size: 16px; color: var(--accent); }
    .status-card-title { font-weight: 500; flex: 1; }
    .status-badge {
      padding: 3px 10px;
      border-radius: 12px;
      font-size: 11px;
      font-weight: 500;
      text-transform: uppercase;
      letter-spacing: 0.3px;
    }
    .status-badge.idle { background: var(--border); color: var(--text-secondary); }
    .status-badge.indexing { background: var(--vscode-charts-yellow, #e9a700); color: #000; }
    .status-badge.watching { background: var(--vscode-charts-purple, #a855f7); color: #fff; }
    .status-badge.ready { background: var(--vscode-charts-green, #22c55e); color: #fff; }
    .status-badge.error { background: var(--vscode-errorForeground, #f14c4c); color: #fff; }
    .status-badge.offline { background: var(--vscode-errorForeground, #f14c4c); color: #fff; }
    .status-badge.online { background: var(--vscode-charts-green, #22c55e); color: #fff; }
    .status-card-body { padding: 16px; }
    .status-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 8px 0;
      border-bottom: 1px solid var(--border-subtle);
    }
    .status-row:last-child { border-bottom: none; }
    .status-label { color: var(--text-secondary); font-size: 12px; }
    .status-value { font-weight: 500; font-size: 13px; }

    /* Progress bar styles */
    .progress-container { margin-bottom: 16px; }
    .progress-info {
      display: flex;
      justify-content: space-between;
      margin-bottom: 8px;
      font-size: 12px;
    }
    #progress-text { color: var(--text-primary); }
    #progress-percent { color: var(--accent); font-weight: 600; }
    .progress-bar {
      height: 6px;
      background: var(--border);
      border-radius: 3px;
      overflow: hidden;
    }
    .progress-fill {
      height: 100%;
      background: linear-gradient(90deg, var(--accent), var(--vscode-charts-green, #22c55e));
      border-radius: 3px;
      transition: width 0.3s ease;
    }
    .current-file {
      margin-top: 8px;
      font-size: 11px;
      color: var(--text-muted);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .current-file::before {
      content: '\\eb68';
      font-family: codicon;
      margin-right: 6px;
      opacity: 0.7;
    }
    `;
  }

  _getScript() {
    return `
    const vscode = acquireVsCodeApi();
    let pollInterval = null;
    let isStatusSection = false;

    function updateSetting(key, value) {
      vscode.postMessage({ command: 'updateSetting', key, value });
    }
    function openVsCodeSettings() {
      vscode.postMessage({ command: 'openVsCodeSettings' });
    }
    document.querySelectorAll('.nav-item').forEach(btn => {
      btn.addEventListener('click', () => {
        vscode.postMessage({ command: 'setSection', section: btn.dataset.section });
      });
    });

    // Status polling functions
    function formatNumber(num) {
      return num != null ? num.toLocaleString() : '--';
    }

    function updateStatusUI(data) {
      const statusBadge = document.getElementById('status-badge');
      const progressContainer = document.getElementById('progress-container');
      const progressText = document.getElementById('progress-text');
      const progressPercent = document.getElementById('progress-percent');
      const progressFill = document.getElementById('progress-fill');
      const currentFile = document.getElementById('current-file');
      const stateValue = document.getElementById('state-value');
      const pointsValue = document.getElementById('points-value');
      const watcherValue = document.getElementById('watcher-value');
      const qdrantValue = document.getElementById('qdrant-value');

      if (!statusBadge) return; // Not on status section

      const state = data.indexing_state || 'idle';
      const progress = data.progress;

      // Update badge
      statusBadge.textContent = state.charAt(0).toUpperCase() + state.slice(1);
      statusBadge.className = 'status-badge ' + state;

      // Update progress bar if indexing
      if (state === 'indexing' && progress) {
        progressContainer.style.display = 'block';
        const processed = progress.files_processed || 0;
        const total = progress.total_files || 1;
        const percent = Math.round((processed / total) * 100);

        progressText.textContent = formatNumber(processed) + ' / ' + formatNumber(total) + ' files';
        progressPercent.textContent = percent + '%';
        progressFill.style.width = percent + '%';

        if (progress.current_file) {
          const shortPath = progress.current_file.split('/').slice(-2).join('/');
          currentFile.textContent = shortPath;
          currentFile.style.display = 'block';
        } else {
          currentFile.style.display = 'none';
        }
      } else {
        progressContainer.style.display = 'none';
      }

      // Update details
      stateValue.textContent = state.charAt(0).toUpperCase() + state.slice(1);
      pointsValue.textContent = formatNumber(data.points_count);
      watcherValue.textContent = data.watcher_active ? 'Active' : 'Inactive';
      watcherValue.style.color = data.watcher_active ? 'var(--vscode-charts-green, #22c55e)' : 'var(--text-secondary)';
      qdrantValue.textContent = data.qdrant_healthy ? 'Connected' : 'Disconnected';
      qdrantValue.style.color = data.qdrant_healthy ? 'var(--vscode-charts-green, #22c55e)' : 'var(--vscode-errorForeground, #f14c4c)';
    }

    function updateConnectionUI(isConnected, endpoint) {
      const connectionBadge = document.getElementById('connection-badge');
      const endpointValue = document.getElementById('endpoint-value');
      const lastCheckedValue = document.getElementById('last-checked-value');

      if (!connectionBadge) return;

      connectionBadge.textContent = isConnected ? 'Online' : 'Offline';
      connectionBadge.className = 'status-badge ' + (isConnected ? 'online' : 'offline');
      endpointValue.textContent = endpoint || '--';
      lastCheckedValue.textContent = new Date().toLocaleTimeString();
    }

    async function pollStatus() {
      if (!STATUS_ENDPOINT) {
        updateConnectionUI(false, 'Not configured');
        return;
      }

      try {
        const params = new URLSearchParams();
        if (WORKSPACE_PATH) params.set('workspace_path', WORKSPACE_PATH);

        const url = STATUS_ENDPOINT + '/api/v1/indexing/status' + (params.toString() ? '?' + params.toString() : '');
        const response = await fetch(url, {
          method: 'GET',
          headers: { 'Accept': 'application/json' }
        });

        if (response.ok) {
          const data = await response.json();
          updateStatusUI(data);
          updateConnectionUI(true, STATUS_ENDPOINT);

          // Poll faster during indexing
          const newInterval = data.indexing_state === 'indexing' ? 1500 : 5000;
          if (pollInterval && pollInterval._interval !== newInterval) {
            clearInterval(pollInterval);
            pollInterval = setInterval(pollStatus, newInterval);
            pollInterval._interval = newInterval;
          }
        } else {
          updateConnectionUI(false, STATUS_ENDPOINT);
        }
      } catch (error) {
        updateConnectionUI(false, STATUS_ENDPOINT);
        console.log('Status poll error:', error.message);
      }
    }

    // Start polling if on status section
    if (document.getElementById('indexing-status-card')) {
      isStatusSection = true;
      pollStatus();
      pollInterval = setInterval(pollStatus, 3000);
      pollInterval._interval = 3000;
    }
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

module.exports = { SettingsWebviewProvider, SETTINGS_SCHEMA };
