// OraFlow extension uninstall hook (referenced by package.json
// "vscode:uninstall"). VS Code runs this in a bare Node process when the
// extension is fully uninstalled (not on upgrade). There is NO vscode API and
// no knowledge of which workspaces are/were open here, so we rely on the
// managed-workspaces registry written by the extension at activation/config
// time to find every workspace we touched and undo our managed edits.
//
// What it cleans (per recorded workspace):
//   - the managed `oraflow` server entry in `.vscode/mcp.json`
//   - the managed block in `.github/copilot-instructions.md`
// Files/dirs that become empty as a result are removed.
//
// What it deliberately preserves:
//   - user/hand-written mcp.json servers and copilot-instructions content
//   - credentials (`~/.oraflow/credentials.toml`, `~/.oraflow/jira.toml`)
//
// The hook is best-effort: every step is wrapped so a single failure never
// aborts cleanup of the remaining workspaces.
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');

const SERVER_KEY = 'oraflow';
const AGENT_BEGIN = '<!-- BEGIN ORAFLOW AGENT INSTRUCTIONS (managed by OraFlow extension; do not edit between markers) -->';
const AGENT_END = '<!-- END ORAFLOW AGENT INSTRUCTIONS -->';

function registryPath() {
  return path.join(os.homedir(), '.oraflow', 'managed-workspaces.json');
}

function readRegistry() {
  try {
    const raw = fs.readFileSync(registryPath(), 'utf8').replace(/^\uFEFF/, '');
    const parsed = JSON.parse(raw);
    if (parsed && Array.isArray(parsed.workspaces)) {
      return parsed.workspaces.filter((entry) => typeof entry === 'string' && entry.length);
    }
  } catch (_e) { /* missing or malformed -> nothing recorded */ }
  return [];
}

function isManagedOraFlowServer(server) {
  if (!server || typeof server !== 'object') return false;
  if (server.env && server.env.ORAFLOW_MANAGED_BY_EXTENSION === 'true') return true;
  const command = String(server.command || '').toLowerCase().replace(/\\/g, '/');
  if (!command) return false;
  return command.includes('/enterpriserx.oraflow-') ||
    command.endsWith('/oraflow-mcp.exe') ||
    command.endsWith('/oraflow-mcp');
}

function removeIfEmptyDir(dir) {
  try { fs.rmdirSync(dir); } catch (_e) { /* non-empty or missing -> keep */ }
}

function cleanMcp(root) {
  const target = path.join(root, '.vscode', 'mcp.json');
  let parsed;
  try { parsed = JSON.parse(fs.readFileSync(target, 'utf8').replace(/^\uFEFF/, '')); }
  catch (_e) { return; }
  if (!parsed || typeof parsed !== 'object' || !parsed.servers || typeof parsed.servers !== 'object') return;
  if (!isManagedOraFlowServer(parsed.servers[SERVER_KEY])) return; // leave user/unmanaged entries
  delete parsed.servers[SERVER_KEY];

  const otherServers = Object.keys(parsed.servers).length;
  const otherTopKeys = Object.keys(parsed).filter((k) => k !== 'servers').length;
  if (otherServers === 0 && otherTopKeys === 0) {
    try { fs.unlinkSync(target); } catch (_e) { return; }
    removeIfEmptyDir(path.join(root, '.vscode'));
  } else {
    try { fs.writeFileSync(target, JSON.stringify(parsed, null, 2) + '\n', 'utf8'); } catch (_e) { /* best effort */ }
  }
}

function cleanInstructions(root) {
  const target = path.join(root, '.github', 'copilot-instructions.md');
  let text;
  try { text = fs.readFileSync(target, 'utf8').replace(/^\uFEFF/, ''); }
  catch (_e) { return; }
  const begin = text.indexOf(AGENT_BEGIN);
  const end = text.indexOf(AGENT_END);
  if (begin === -1 || end === -1 || end < begin) return; // no managed block

  const before = text.slice(0, begin);
  const after = text.slice(end + AGENT_END.length).replace(/^\r?\n/, '');
  const updated = before + after;
  if (updated.trim().length === 0) {
    try { fs.unlinkSync(target); } catch (_e) { return; }
    removeIfEmptyDir(path.join(root, '.github'));
  } else {
    try { fs.writeFileSync(target, updated, 'utf8'); } catch (_e) { /* best effort */ }
  }
}

function main() {
  for (const root of readRegistry()) {
    try { cleanMcp(root); } catch (_e) { /* keep going */ }
    try { cleanInstructions(root); } catch (_e) { /* keep going */ }
  }
  try { fs.unlinkSync(registryPath()); } catch (_e) { /* already gone */ }
  removeIfEmptyDir(path.join(os.homedir(), '.oraflow'));
}

main();
