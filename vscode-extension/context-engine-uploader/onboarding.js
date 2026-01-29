const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const STACK_REPO_URL = 'https://github.com/m1rl0k/Context-Engine.git';
const STACK_DIRNAME = 'Context-Engine';
const LAST_STACK_PATH_KEY = 'contextEngineUploader.lastStackPath';
const ONBOARDING_PROMPT_KEY = 'contextEngineUploader.onboardingPrompted';

function exists(p) {
  try {
    return !!(p && fs.existsSync(p));
  } catch (_) {
    return false;
  }
}

function defaultCloneParentPath() {
  try {
    const home = os.homedir();
    if (!home) {
      return undefined;
    }
    const docs = path.join(home, 'Documents');
    if (exists(docs)) {
      return docs;
    }
    if (exists(home)) {
      return home;
    }
    return undefined;
  } catch (_) {
    return undefined;
  }
}

function createOnboardingManager(deps) {
  const vscode = deps.vscode;
  const context = deps.context;
  const log = deps.log;
  const appendOutput = deps.appendOutput;
  const showOutput = deps.showOutput;

  function append(line) {
    if (typeof appendOutput === 'function') {
      appendOutput(`${line}${line.endsWith('\n') ? '' : '\n'}`);
    }
  }

  async function pickParentFolder() {
    const defaultPath = defaultCloneParentPath();
    const defaultUri = defaultPath ? vscode.Uri.file(defaultPath) : undefined;
    const selection = await vscode.window.showOpenDialog({
      title: 'Select folder for Context Engine stack',
      canSelectFiles: false,
      canSelectFolders: true,
      canSelectMany: false,
      openLabel: 'Use Folder',
      defaultUri,
    });
    if (!selection || !selection.length) {
      return undefined;
    }
    return selection[0].fsPath;
  }

  async function confirmClone(targetPath) {
    const result = await vscode.window.showInformationMessage(
      `Clone Context Engine repo into:\n${targetPath}\n\nand run \'docker compose up -d\'?`,
      { modal: true },
      'Clone & Start',
      'Cancel'
    );
    return result === 'Clone & Start';
  }

  async function confirmStart(targetPath) {
    const result = await vscode.window.showInformationMessage(
      `Run \'docker compose up -d\' in:\n${targetPath}?`,
      { modal: true },
      'Start Stack',
      'Cancel'
    );
    return result === 'Start Stack';
  }

  function getSavedStackPath() {
    try {
      if (context && context.globalState && typeof context.globalState.get === 'function') {
        const raw = context.globalState.get(LAST_STACK_PATH_KEY);
        return typeof raw === 'string' ? raw : undefined;
      }
    } catch (_) {
    }
    return undefined;
  }

  function saveStackPath(stackPath) {
    try {
      if (context && context.globalState && typeof context.globalState.update === 'function') {
        context.globalState.update(LAST_STACK_PATH_KEY, stackPath || undefined).catch(() => { });
      }
    } catch (_) {
    }
  }

  function ensureDir(dirPath) {
    try {
      fs.mkdirSync(dirPath, { recursive: true });
    } catch (error) {
      throw new Error(`Failed to create directory ${dirPath}: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  function runCommand(command, args, options) {
    return new Promise((resolve, reject) => {
      const child = spawn(command, args, { ...options, env: { ...process.env, ...(options && options.env ? options.env : {}) } });
      if (child.stdout) {
        child.stdout.on('data', data => {
          append(`[${command}] ${data.toString()}`);
        });
      }
      if (child.stderr) {
        child.stderr.on('data', data => {
          append(`[${command}] ${data.toString()}`);
        });
      }
      child.on('error', error => {
        reject(error);
      });
      child.on('close', code => {
        if (code === 0) {
          resolve();
        } else {
          reject(new Error(`${command} exited with code ${code}`));
        }
      });
    });
  }

  async function runGitClone(parentPath, targetPath) {
    ensureDir(parentPath);
    if (exists(targetPath)) {
      append(`[onboarding] Target folder already exists at ${targetPath}; skipping clone.`);
      return;
    }
    append(`[onboarding] Cloning ${STACK_REPO_URL} into ${targetPath}`);
    await runCommand('git', ['clone', STACK_REPO_URL, targetPath], { cwd: parentPath });
  }

  function resolveDockerComposeInvocation() {
    try {
      const probe = spawnSync('docker', ['compose', 'version']);
      if (!probe.error && probe.status === 0) {
        return { command: 'docker', args: ['compose', 'up', '-d'] };
      }
    } catch (_) {
      // ignore
    }
    try {
      const legacy = spawnSync('docker-compose', ['--version']);
      if (!legacy.error && legacy.status === 0) {
        return { command: 'docker-compose', args: ['up', '-d'] };
      }
    } catch (_) {
      // ignore
    }
    throw new Error('Docker Compose is not available (expected "docker compose" or "docker-compose").');
  }

  async function runDockerCompose(targetPath) {
    const invocation = resolveDockerComposeInvocation();
    append(`[onboarding] Running ${invocation.command} ${invocation.args.join(' ')} in ${targetPath}`);
    await runCommand(invocation.command, invocation.args, { cwd: targetPath });
  }

  function looksLikeStackRoot(targetPath) {
    try {
      if (!targetPath || !exists(targetPath)) {
        return false;
      }
      const composeFile = path.join(targetPath, 'docker-compose.yml');
      return exists(composeFile);
    } catch (_) {
      return false;
    }
  }

  async function startStackAtPath(targetPath) {
    if (!targetPath || !exists(targetPath)) {
      vscode.window.showErrorMessage('Context Engine onboarding: saved stack folder does not exist.');
      return;
    }
    if (!looksLikeStackRoot(targetPath)) {
      vscode.window.showWarningMessage('Context Engine onboarding: selected folder does not look like a Context Engine stack (missing docker-compose.yml).');
    }

    const confirmed = await confirmStart(targetPath);
    if (!confirmed) {
      return;
    }

    if (typeof showOutput === 'function') {
      showOutput();
    }
    await vscode.window.withProgress({
      location: vscode.ProgressLocation.Notification,
      title: 'Starting Context Engine stack',
      cancellable: false,
    }, async progress => {
      progress.report({ message: 'Running docker compose…' });
      await runDockerCompose(targetPath);
    });

    vscode.window.showInformationMessage('Context Engine stack start requested.', 'Open Folder', 'Done').then(choice => {
      if (choice === 'Open Folder') {
        vscode.commands.executeCommand('vscode.openFolder', vscode.Uri.file(targetPath), true);
      }
    });
  }

  async function startSavedStack() {
    const saved = getSavedStackPath();
    if (saved) {
      return startStackAtPath(saved);
    }

    const picked = await vscode.window.showOpenDialog({
      title: 'Select existing Context Engine stack folder',
      canSelectFiles: false,
      canSelectFolders: true,
      canSelectMany: false,
      openLabel: 'Use Folder',
    });
    if (!picked || !picked.length) {
      return;
    }
    const targetPath = picked[0].fsPath;
    saveStackPath(targetPath);
    return startStackAtPath(targetPath);
  }

  async function cloneAndStartStack() {
    try {
      const parentPath = await pickParentFolder();
      if (!parentPath) {
        return;
      }
      const targetPath = path.join(parentPath, STACK_DIRNAME);
      const confirmed = await confirmClone(targetPath);
      if (!confirmed) {
        return;
      }
      if (typeof showOutput === 'function') {
        showOutput();
      }
      await vscode.window.withProgress({
        location: vscode.ProgressLocation.Notification,
        title: 'Setting up Context Engine stack',
        cancellable: false,
      }, async progress => {
        progress.report({ message: 'Cloning repository…' });
        await runGitClone(parentPath, targetPath);
        progress.report({ message: 'Starting docker compose…' });
        await runDockerCompose(targetPath);
      });

      saveStackPath(targetPath);
      vscode.window.showInformationMessage('Context Engine stack cloned and docker compose started.', 'Open Folder', 'Done').then(choice => {
        if (choice === 'Open Folder') {
          vscode.commands.executeCommand('vscode.openFolder', vscode.Uri.file(targetPath), true);
        }
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      log(`Clone & Compose onboarding failed: ${message}`);
      vscode.window.showErrorMessage(`Context Engine onboarding failed: ${message}`);
    }
  }

  async function checkOnboarding(config, configResolver) {
    try {
      if (!config || !configResolver) {
        return;
      }
      const endpoint = (config.get('endpoint') || '').trim();
      const resolved = configResolver.resolveTargetPathFromConfig(config);
      const targetPath = resolved && resolved.path ? String(resolved.path).trim() : '';
      const needsSetup = !endpoint || !targetPath;

      if (needsSetup && context && context.workspaceState) {
        const alreadyPrompted = !!context.workspaceState.get(ONBOARDING_PROMPT_KEY);
        if (!alreadyPrompted) {
          await context.workspaceState.update(ONBOARDING_PROMPT_KEY, true);
          vscode.window.showInformationMessage(
            'Context Engine Uploader: finish setup for this workspace to start indexing/uploading.',
            'Setup Workspace',
            'Later'
          ).then(choice => {
            if (choice === 'Setup Workspace') {
              vscode.commands.executeCommand('contextEngineUploader.setupWorkspace').catch(error => {
                const message = error instanceof Error ? error.message : String(error);
                log(`Failed to execute setupWorkspace command: ${message}`);
              });
            }
          });
        }
      }
    } catch (_) {
      // Ignore onboarding check errors to prevent extension activation failure
    }
  }

  /**
   * Check if the local Docker stack is running and healthy.
   * Returns { healthy: boolean, endpoint: string }
   */
  async function checkLocalDockerHealth() {
    const endpoint = 'http://localhost:8004';
    try {
      const fetchFn = typeof fetch === 'function' ? fetch : null;
      if (!fetchFn) {
        return { healthy: false, endpoint };
      }
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 2000);
      const res = await fetchFn(`${endpoint}/health`, {
        method: 'GET',
        signal: controller.signal
      });
      clearTimeout(timeout);
      return { healthy: !!res.ok, endpoint };
    } catch (_) {
      return { healthy: false, endpoint };
    }
  }

  /**
   * Poll for Docker stack health with progress indicator.
   * Called after cloneAndStartStack to wait for services.
   */
  async function waitForDockerReady(maxWaitMs = 60000) {
    const startTime = Date.now();
    const pollInterval = 2000;

    return vscode.window.withProgress({
      location: vscode.ProgressLocation.Notification,
      title: 'Waiting for Docker services to start',
      cancellable: true,
    }, async (progress, token) => {
      while (Date.now() - startTime < maxWaitMs) {
        if (token.isCancellationRequested) {
          return false;
        }
        const elapsed = Date.now() - startTime;
        const pct = Math.min(90, (elapsed / maxWaitMs) * 100);
        progress.report({ message: 'Checking health...', increment: pct / 10 });

        const { healthy } = await checkLocalDockerHealth();
        if (healthy) {
          progress.report({ message: 'Services ready!', increment: 100 });
          return true;
        }
        await new Promise(resolve => setTimeout(resolve, pollInterval));
      }
      return false;
    });
  }

  return {
    cloneAndStartStack,
    startSavedStack,
    getSavedStackPath,
    checkOnboarding,
    checkLocalDockerHealth,
    waitForDockerReady,
    dispose: () => { },
  };
}

module.exports = {
  createOnboardingManager,
  STACK_REPO_URL,
  STACK_DIRNAME,
};
