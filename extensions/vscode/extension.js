const vscode = require('vscode');
const childProcess = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

function bundledBackend(context) {
  const exe = process.platform === 'win32' ? 'oraflow-mcp.exe' : 'oraflow-mcp';
  return path.join(context.extensionPath, 'bin', `${process.platform}-${process.arch}`, 'oraflow-mcp', exe);
}
function credentialsPath() {
  return path.join(os.homedir(), '.oraflow', 'credentials.toml');
}
function jiraCredentialsPath() {
  return path.join(os.homedir(), '.oraflow', 'jira.toml');
}

function hardenCredentialFile(target) {
  try { fs.chmodSync(target, 0o600); } catch (_e) { /* best effort */ }
  if (process.platform !== 'win32') return true;
  try {
    const domain = process.env.USERDOMAIN || os.hostname();
    const user = process.env.USERNAME || os.userInfo().username;
    const identity = user.includes('\\') ? user : `${domain}\\${user}`;
    childProcess.execFileSync('icacls', [target, '/inheritance:r'], { windowsHide: true, stdio: 'ignore' });
    childProcess.execFileSync('icacls', [target, '/grant:r', `${identity}:F`, 'SYSTEM:F', 'Administrators:F'], { windowsHide: true, stdio: 'ignore' });
    return true;
  } catch (error) {
    console.error('OraFlow: failed to harden credential ACLs', error);
    return false;
  }
}
function bundledTnsPaths(context) {
  return [
    path.join(context.extensionPath, 'oracle-network', 'admin', 'tnsnames.ora'),
    path.join(context.extensionPath, 'oracle-network', 'admin', 'cloud-tnsnames.ora')
  ];
}
function bundledSchemaPath(context) {
  return path.join(context.extensionPath, 'schemas');
}
function bundledInstructionsPath(context) {
  return path.join(context.extensionPath, 'assets', 'ORAFLOW_INSTRUCTIONS.md');
}
function bundledCustomersPath(context) {
  return path.join(context.extensionPath, 'assets', 'customers.toml');
}
function bundledHelpTopicsPath(context) {
  return path.join(context.extensionPath, 'assets', 'help-topics.toml');
}
function bundledAgentInstructionsPath(context) {
  return path.join(context.extensionPath, 'assets', 'oraflow-agent-instructions.md');
}
function bundledSqlplus12Home(context) {
  return path.join(context.extensionPath, 'bin', `${process.platform}-${process.arch}`, 'sqlplus12');
}

// Registry of workspaces where this extension has written a managed mcp.json /
// copilot-instructions block. The `vscode:uninstall` hook runs in a bare Node
// process with no vscode API and no knowledge of open workspaces, so it relies
// on this registry to find and clean every managed workspace at uninstall time.
function managedWorkspacesRegistryPath() {
  return path.join(os.homedir(), '.oraflow', 'managed-workspaces.json');
}
function recordManagedWorkspace(root) {
  if (!root) return;
  try {
    const file = managedWorkspacesRegistryPath();
    fs.mkdirSync(path.dirname(file), { recursive: true });
    let list = [];
    try {
      const parsed = JSON.parse(fs.readFileSync(file, 'utf8'));
      if (parsed && Array.isArray(parsed.workspaces)) {
        list = parsed.workspaces.filter((entry) => typeof entry === 'string' && entry.length);
      }
    } catch (_e) { /* missing or malformed registry -> start fresh */ }
    const normalized = path.normalize(root);
    const already = list.some((entry) => path.normalize(entry).toLowerCase() === normalized.toLowerCase());
    if (!already) {
      list.push(normalized);
      fs.writeFileSync(file, JSON.stringify({ workspaces: list }, null, 2) + '\n', 'utf8');
    }
  } catch (error) {
    console.error('OraFlow: failed to record managed workspace in registry', error);
  }
}

function workspaceRoot() {
  const folders = vscode.workspace.workspaceFolders;
  return folders && folders.length ? folders[0].uri.fsPath : null;
}
function oraflowWorkspaceDir() {
  const root = workspaceRoot();
  if (!root) return null;
  return path.join(root, 'OraFlow');
}
function sessionPath() {
  const dir = oraflowWorkspaceDir();
  return dir ? path.join(dir, 'session.json') : null;
}
function readActiveTarget() {
  const file = sessionPath();
  if (!file || !fs.existsSync(file)) return null;
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); }
  catch (_e) { return { error: 'MALFORMED_SESSION', path: file }; }
}
function writeActiveTarget(target) {
  const file = sessionPath();
  if (!file) throw new Error('Open a workspace folder first.');
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(target, null, 2) + '\n', 'utf8');
}

const SCHEMA_SCOPES = {
  trexone_data: {
    schema_key: 'trexone_data',
    schema: 'TREXONE_DATA',
    schemas: ['TREXONE_DATA'],
    layer: 'oltp',
    label: 'TREXONE_DATA',
    aliases: ['trexone_data', 'data', 'oltp']
  },
  trexone_aud_data: {
    schema_key: 'trexone_aud_data',
    schema: 'TREXONE_AUD_DATA',
    schemas: ['TREXONE_AUD_DATA'],
    layer: 'aud',
    label: 'TREXONE_AUD_DATA',
    aliases: ['trexone_aud_data', 'aud', 'audit']
  },
  trexone_dw_data: {
    schema_key: 'trexone_dw_data',
    schema: 'TREXONE_DW_DATA',
    schemas: ['TREXONE_DW_DATA'],
    layer: 'dw',
    label: 'TREXONE_DW_DATA',
    aliases: ['trexone_dw_data', 'dw', 'warehouse']
  },
  trexone_ods_data: {
    schema_key: 'trexone_ods_data',
    schema: 'TREXONE_ODS_DATA',
    schemas: ['TREXONE_ODS_DATA'],
    layer: 'ods',
    label: 'TREXONE_ODS_DATA',
    aliases: ['trexone_ods_data', 'ods']
  },
  olap: {
    schema_key: 'olap',
    schema: 'OLAP',
    schemas: ['TREXONE_AUD_DATA', 'TREXONE_DW_DATA', 'TREXONE_ODS_DATA'],
    layer: 'olap',
    label: 'OLAP (TREXONE_AUD_DATA + TREXONE_DW_DATA + TREXONE_ODS_DATA)',
    aliases: ['olap']
  },
  all: {
    schema_key: 'all',
    schema: 'ALL',
    schemas: ['TREXONE_DATA', 'TREXONE_AUD_DATA', 'TREXONE_DW_DATA', 'TREXONE_ODS_DATA'],
    layer: 'all',
    label: 'ALL schemas',
    aliases: ['all']
  }
};

const SCHEMA_ALIAS_TO_KEY = Object.fromEntries(
  Object.values(SCHEMA_SCOPES).flatMap((scope) => scope.aliases.map((alias) => [alias, scope.schema_key]))
);

function normalizeSchemaScope(value) {
  const token = String(value || '').trim().toLowerCase();
  const key = SCHEMA_ALIAS_TO_KEY[token] || token;
  return SCHEMA_SCOPES[key] || null;
}


function schemaSummary(target) {
  if (!target || target.error) return 'TREXONE_DATA';
  const scope = normalizeSchemaScope(target.schema_key || target.schema || target.layer);
  if (scope) return scope.label;
  if (Array.isArray(target.schemas) && target.schemas.length > 1) return `${target.schema || target.schema_key || target.layer} [${target.schemas.join(', ')}]`;
  return target.schema || String(target.layer || 'oltp').toUpperCase();
}

async function setupCredentials() {
  const target = credentialsPath();
  fs.mkdirSync(path.dirname(target), { recursive: true });
  const created = !fs.existsSync(target);
  if (created) {
    fs.writeFileSync(target, credentialsTemplate(), { encoding: 'utf8', mode: 0o600 });
  }
  const hardened = hardenCredentialFile(target);
  const doc = await vscode.workspace.openTextDocument(target);
  await vscode.window.showTextDocument(doc);
  vscode.window.showInformationMessage(
    created
      ? `Created OraFlow credentials template at ${target}. Fill in the profiles you need and save.`
      : `Opened OraFlow credentials at ${target}.`
  );
  if (!hardened) {
    vscode.window.showWarningMessage(`OraFlow could not verify restricted ACLs on ${target}. Check file permissions before adding passwords.`);
  }
}

async function setupJiraCredentials() {
  const target = jiraCredentialsPath();
  fs.mkdirSync(path.dirname(target), { recursive: true });
  const created = !fs.existsSync(target);
  if (created) {
    fs.writeFileSync(target, jiraCredentialsTemplate(), { encoding: 'utf8', mode: 0o600 });
  }
  const hardened = hardenCredentialFile(target);
  const doc = await vscode.workspace.openTextDocument(target);
  await vscode.window.showTextDocument(doc);
  vscode.window.showInformationMessage(
    created
      ? `Created OraFlow Jira credentials template at ${target}. Add your Atlassian API token, save, then run jira_credentials_doctor.`
      : `Opened OraFlow Jira credentials at ${target}.`
  );
  if (!hardened) {
    vscode.window.showWarningMessage(`OraFlow could not verify restricted ACLs on ${target}. Check file permissions before adding your Jira API token.`);
  }
}

function jiraCredentialsTemplate() {
  return `# JiraFlow credentials. Generate an Atlassian API token at:
# https://id.atlassian.com/manage-profile/security/api-tokens
# JiraFlow is read-only; OraFlow uses these credentials only for explicit Jira tools.
base_url = "https://mckesson.atlassian.net"
email = ""
api_token = ""
timeout_s = 30
`;
}

function credentialsTemplate() {
  return `schema_version = 1

# Fill in only the profiles you need. Use profile names in chat; never paste passwords into Copilot.
[onprem.prod]
username = ""
password = ""

[onprem.qa]
username = ""
password = ""

[onprem.uat]
username = ""
password = ""

[onprem.dev]
username = ""
password = ""

[cloud.qa]
username = ""
password = ""

[cloud.dev]
username = ""
password = ""
`;
}

function readMcpConfig(target) {
  if (!fs.existsSync(target)) return { servers: {} };
  try {
    const parsed = JSON.parse(fs.readFileSync(target, 'utf8'));
    if (!parsed || typeof parsed !== 'object') return { servers: {} };
    if (!parsed.servers || typeof parsed.servers !== 'object') parsed.servers = {};
    return parsed;
  } catch (_e) {
    throw new Error(`Existing MCP config is not valid JSON: ${target}`);
  }
}

function mcpServerConfig(context, root) {
  const backend = bundledBackend(context);
  const tnsPaths = bundledTnsPaths(context);
  const schemaPath = bundledSchemaPath(context);
  const instructionsPath = bundledInstructionsPath(context);
  const customersPath = bundledCustomersPath(context);
  const helpTopicsPath = bundledHelpTopicsPath(context);
  const agentInstructionsPath = bundledAgentInstructionsPath(context);
  const sqlplus12Home = bundledSqlplus12Home(context);
  const sqlplus12Exe = path.join(sqlplus12Home, 'bin', process.platform === 'win32' ? 'sqlplus.exe' : 'sqlplus');
  const instantClientDir = path.join(context.extensionPath, 'bin', `${process.platform}-${process.arch}`, 'instantclient');
  const instantClientDll = path.join(instantClientDir, process.platform === 'win32' ? 'oci.dll' : 'libclntsh.so');
  const missing = [backend, ...tnsPaths, schemaPath, instructionsPath, customersPath, helpTopicsPath, agentInstructionsPath, sqlplus12Exe, instantClientDir, instantClientDll].filter((candidate) => !fs.existsSync(candidate));

  const env = {
    ORAFLOW_MANAGED_BY_EXTENSION: 'true',
    ORAFLOW_EXTENSION_ID: 'enterpriserx.oraflow',
    ORAFLOW_WORKSPACE_DIR: root,
    ORAFLOW_TNSNAMES_PATHS: tnsPaths.join(';'),
    ORAFLOW_SCHEMA_CATALOG_PATH: schemaPath,
    ORAFLOW_INSTRUCTIONS_PATH: instructionsPath,
    ORAFLOW_CUSTOMERS_PATH: customersPath,
    ORAFLOW_HELP_TOPICS_PATH: helpTopicsPath,
    ORAFLOW_CREDENTIALS_PATH: credentialsPath(),
    ORAFLOW_SQLPLUS12_HOME: sqlplus12Home,
    ORAFLOW_THICK_MODE: 'true',
    ORAFLOW_ORACLE_CLIENT_LIB_DIR: instantClientDir,
    // Force python-oracledb/IC23 to use OUR clean bundled sqlnet.ora and
    // tnsnames.ora. Legacy PROD auth that requires the Toad-style 12.2 OCI
    // behavior is handled by the bundled SQL*Plus 12.2 fallback exposed via
    // ORAFLOW_SQLPLUS12_HOME above.
    TNS_ADMIN: path.dirname(tnsPaths[0]),
    // Clear ORACLE_HOME so an old client install on the user's machine cannot
    // influence DLL search and shadow our bundled Instant Client.
    ORACLE_HOME: ''
  };

  return {
    backend,
    missing,
    server: { type: 'stdio', command: backend, args: [], env }
  };
}

function isManagedOraFlowServer(server) {
  const command = String((server && server.command) || '').toLowerCase();
  if (!command) return false;
  const normalized = command.replace(/\\/g, '/');
  return normalized.includes('/enterpriserx.oraflow-') || normalized.endsWith('/oraflow-mcp.exe') || normalized.endsWith('/oraflow-mcp');
}

function sameJson(left, right) {
  return JSON.stringify(left) === JSON.stringify(right);
}

function refreshManagedMcpConfig(context) {
  const folders = vscode.workspace.workspaceFolders;
  if (!folders || folders.length === 0) return;

  const root = folders[0].uri.fsPath;
  const target = path.join(root, '.vscode', 'mcp.json');
  if (!fs.existsSync(target)) return;

  try {
    const mcp = readMcpConfig(target);
    const existing = mcp.servers && mcp.servers.oraflow;
    if (!isManagedOraFlowServer(existing)) return;

    const next = mcpServerConfig(context, root);
    if (next.missing.length > 0) return;
    if (sameJson(existing, next.server)) {
      recordManagedWorkspace(root);
      const agentResult = writeWorkspaceAgentInstructions(root, context);
      if (agentResult.action !== 'unchanged') {
        console.log(`OraFlow: refreshed managed Copilot instructions after extension activation: ${agentResult.path}`);
      }
      return;
    }

    mcp.servers.oraflow = next.server;
    fs.writeFileSync(target, JSON.stringify(mcp, null, 2), 'utf8');
    recordManagedWorkspace(root);
    writeWorkspaceAgentInstructions(root, context);
    console.log(`OraFlow: refreshed managed MCP config after extension upgrade: ${target}`);
  } catch (error) {
    console.error('OraFlow: failed to refresh managed MCP config', error);
  }
}

const ORAFLOW_AGENT_BEGIN = '<!-- BEGIN ORAFLOW AGENT INSTRUCTIONS (managed by OraFlow extension; do not edit between markers) -->';
const ORAFLOW_AGENT_END = '<!-- END ORAFLOW AGENT INSTRUCTIONS -->';

/**
 * Write or refresh `.github/copilot-instructions.md` so that Copilot agent mode
 * picks up the OraFlow workflow + safety guardrails BEFORE the MCP server
 * starts (and even on turns where the MCP `instructions` payload has been
 * compacted out of context).
 *
 * Behavior:
 *   - File missing                    : create with the managed block.
 *   - File exists, no marker present  : append the managed block (preserve
 *                                       all hand-written content above).
 *   - File exists, marker present     : replace only the content between the
 *                                       BEGIN/END markers (preserve content
 *                                       outside).
 *
 * Returns { path, action } where action is
 * 'created' | 'appended' | 'refreshed' | 'unchanged' | 'skipped'.
 */
function writeWorkspaceAgentInstructions(workspaceRoot, context) {
  try {
    const sourcePath = bundledAgentInstructionsPath(context);
    if (!fs.existsSync(sourcePath)) return { path: null, action: 'skipped' };
    const body = fs.readFileSync(sourcePath, 'utf8').trimEnd();
    const block = `${ORAFLOW_AGENT_BEGIN}\n${body}\n${ORAFLOW_AGENT_END}\n`;

    const ghDir = path.join(workspaceRoot, '.github');
    const target = path.join(ghDir, 'copilot-instructions.md');
    fs.mkdirSync(ghDir, { recursive: true });

    if (!fs.existsSync(target)) {
      fs.writeFileSync(target, block, 'utf8');
      return { path: target, action: 'created' };
    }

    const existing = fs.readFileSync(target, 'utf8');
    const beginIdx = existing.indexOf(ORAFLOW_AGENT_BEGIN);
    const endIdx = existing.indexOf(ORAFLOW_AGENT_END);
    if (beginIdx === -1 || endIdx === -1 || endIdx < beginIdx) {
      const sep = existing.endsWith('\n') ? '\n' : '\n\n';
      fs.writeFileSync(target, existing + sep + block, 'utf8');
      return { path: target, action: 'appended' };
    }

    const before = existing.slice(0, beginIdx);
    const afterStart = endIdx + ORAFLOW_AGENT_END.length;
    const after = existing.slice(afterStart).replace(/^\r?\n/, '');
    const updated = before + block + after;
    if (updated === existing) {
      return { path: target, action: 'unchanged' };
    }
    fs.writeFileSync(target, updated, 'utf8');
    return { path: target, action: 'refreshed' };
  } catch (error) {
    console.error('OraFlow: failed to write copilot-instructions.md', error);
    return { path: null, action: 'skipped' };
  }
}

async function configureMcp(context) {
  const folders = vscode.workspace.workspaceFolders;
  if (!folders || folders.length === 0) {
    vscode.window.showErrorMessage('Open a workspace folder first.');
    return;
  }
  const root = folders[0].uri.fsPath;
  const vscodeDir = path.join(root, '.vscode');
  fs.mkdirSync(vscodeDir, { recursive: true });
  const config = mcpServerConfig(context, root);
  const backend = config.backend;
  if (config.missing.length > 0) {
    vscode.window.showErrorMessage(`OraFlow bundle is incomplete. Missing: ${config.missing.join(', ')}`);
    return;
  }
  const target = path.join(vscodeDir, 'mcp.json');
  let mcp;
  try { mcp = readMcpConfig(target); }
  catch (error) { vscode.window.showErrorMessage(error.message); return; }

  mcp.servers.oraflow = config.server;
  fs.writeFileSync(target, JSON.stringify(mcp, null, 2), 'utf8');
  recordManagedWorkspace(root);
  const agentResult = writeWorkspaceAgentInstructions(root, context);
  const agentDetail = (() => {
    switch (agentResult.action) {
      case 'created':   return ` Wrote agent guidance to ${agentResult.path}.`;
      case 'appended':  return ` Appended OraFlow agent guidance to ${agentResult.path}.`;
      case 'refreshed': return ` Refreshed OraFlow agent guidance in ${agentResult.path}.`;
      case 'unchanged': return ' Agent guidance already up to date.';
      default:          return '';
    }
  })();

  const open = await vscode.window.showInformationMessage(
    `OraFlow MCP config written to ${target}. Bundled backend, Instant Client, TNS, schema catalog, and SQL*Plus fallback are wired in.${agentDetail} Start/trust the server from MCP: List Servers.`,
    'Open mcp.json'
  );
  if (open === 'Open mcp.json') {
    const doc = await vscode.workspace.openTextDocument(target);
    await vscode.window.showTextDocument(doc);
  }
}

async function openCredentials() {
  // Deprecated: kept as a thin alias of setupCredentials so any external
  // shortcut referencing oraflow.openCredentials still works. The command is
  // no longer surfaced in the command palette.
  return setupCredentials();
}

function targetSummary(target) {
  if (!target) return 'No active OraFlow target. Ask Copilot agent mode to call the OraFlow MCP tool set_active_target (e.g. "use OraFlow to set the active target to vanderbilt qa").';
  if (target.error) return `Active target file is invalid: ${target.path}`;
  return `${target.display_name || target.customer} ${String(target.env || '').toUpperCase()} · ${schemaSummary(target)} · ${target.profile || '?'} · ${target.tns_alias || '?'}`;
}

function updateStatusBar(context) {
  if (!context.oraflowStatusBar) return;
  const target = readActiveTarget();
  context.oraflowStatusBar.text = target ? `$(database) ${targetSummary(target).split(' · ')[0]}` : '$(database) OraFlow';
  context.oraflowStatusBar.tooltip = `OraFlow by Abdul Aziz Mohammed\n${targetSummary(target)}`;
  context.oraflowStatusBar.backgroundColor = target && String(target.env).toLowerCase() === 'prod'
    ? new vscode.ThemeColor('statusBarItem.errorBackground')
    : undefined;
  context.oraflowStatusBar.show();
}


function activate(context) {
  context.subscriptions.push(vscode.commands.registerCommand('oraflow.setupCredentials', () => setupCredentials()));
  context.subscriptions.push(vscode.commands.registerCommand('oraflow.setupJiraCredentials', () => setupJiraCredentials()));
  context.subscriptions.push(vscode.commands.registerCommand('oraflow.configureMcp', () => configureMcp(context)));
  context.subscriptions.push(vscode.commands.registerCommand('oraflow.openCredentials', () => openCredentials()));
  context.subscriptions.push(vscode.commands.registerCommand('oraflow.showBackendPath', () => vscode.window.showInformationMessage(bundledBackend(context))));
  context.oraflowStatusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  context.oraflowStatusBar.command = 'oraflow.configureMcp';
  context.subscriptions.push(context.oraflowStatusBar);
  refreshManagedMcpConfig(context);
  updateStatusBar(context);
}
function deactivate() {}
module.exports = { activate, deactivate };


