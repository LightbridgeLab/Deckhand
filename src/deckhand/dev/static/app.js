/**
 * Deckhand Dev Console — local testing UI without OpenDeck.
 */

const API_KEY_STORAGE = "deckhand_dev_api_key";
const TILES_STORAGE_V2 = "deckhand_dev_virtual_tiles_v2";
const TILES_STORAGE_V1 = "deckhand_dev_virtual_tiles";
const TILE_COUNT = 6;
const MAX_EVENTS = 200;
const HOOK_SESSION_ID = "dev-session-001";
const CURSOR_HOOK_SESSION_ID = "cursor-dev-001";
const TILE_RETRY_BASE_MS = 5000;
const TILE_FLASH_MS = 500;

const UUID = {
  AGENT_STATUS: "com.deckhand.agent.status",
  AGENT_SLOT: "com.deckhand.agent.slot",
  WIDGET: "com.deckhand.widget",
  SIGNAL: "com.deckhand.signal.trigger",
  ACTION_RUN: "com.deckhand.action.run",
  DASHBOARD: "com.deckhand.agent.dashboard",
};

const HOOK_PRESETS = {
  SessionStart: {
    session_id: HOOK_SESSION_ID,
    hook_event_name: "SessionStart",
    cwd: "/tmp/my-project",
  },
  UserPromptSubmit: {
    session_id: HOOK_SESSION_ID,
    hook_event_name: "UserPromptSubmit",
    cwd: "/tmp/my-project",
  },
  PreToolUse: {
    session_id: HOOK_SESSION_ID,
    hook_event_name: "PreToolUse",
    cwd: "/tmp/my-project",
  },
  Notification: {
    session_id: HOOK_SESSION_ID,
    hook_event_name: "Notification",
    cwd: "/tmp/my-project",
  },
  Stop: {
    session_id: HOOK_SESSION_ID,
    hook_event_name: "Stop",
    cwd: "/tmp/my-project",
  },
  SessionEnd: {
    session_id: HOOK_SESSION_ID,
    hook_event_name: "SessionEnd",
  },
};

const CURSOR_HOOK_PRESETS = {
  sessionStart: {
    session_id: CURSOR_HOOK_SESSION_ID,
    hook_event_name: "sessionStart",
    cwd: "/tmp/cursor-project",
    title: "Fix auth bug",
  },
  beforeSubmitPrompt: {
    session_id: CURSOR_HOOK_SESSION_ID,
    hook_event_name: "beforeSubmitPrompt",
    cwd: "/tmp/cursor-project",
    title: "Fix auth bug",
  },
  preToolUse: {
    session_id: CURSOR_HOOK_SESSION_ID,
    hook_event_name: "preToolUse",
    cwd: "/tmp/cursor-project",
  },
  stop: {
    session_id: CURSOR_HOOK_SESSION_ID,
    hook_event_name: "stop",
    cwd: "/tmp/cursor-project",
  },
  awaitingInput: {
    session_id: CURSOR_HOOK_SESSION_ID,
    hook_event_name: "preToolUse",
    cwd: "/tmp/cursor-project",
    deckhand_status: "awaiting_input",
  },
  sessionEnd: {
    session_id: CURSOR_HOOK_SESSION_ID,
    hook_event_name: "sessionEnd",
  },
};

/** @type {Record<string, { label: string, fields: Record<string, object> }>} */
let actionSchema = {};
let apiKey = "";
let ws = null;
let wsReconnectTimer = null;
let agents = [];
let stateEntries = [];
let actionsList = [];
let signalsList = [];
let lastAgentIds = "";
let lastStateKeys = "";
let lastSignalNames = "";
const stateByKey = new Map();
/** @type {Map<number, { count: number, timer: number | null, pendingLabel: string | null }>} */
const tileRetryState = new Map();
/** @type {Map<number, { title: string, until: number }>} */
const tileFlashState = new Map();

const TB = () => globalThis.DeckhandTileBehavior;

// ---------------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
  bindUi();
  apiKey = sessionStorage.getItem(API_KEY_STORAGE) || "";
  if (apiKey) {
    startApp();
  } else {
    showAuthDialog();
  }
});

function bindUi() {
  const authForm = document.getElementById("auth-form");
  authForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const input = document.getElementById("api-key-input");
    apiKey = input.value.trim();
    if (!apiKey) return;
    sessionStorage.setItem(API_KEY_STORAGE, apiKey);
    document.getElementById("auth-dialog").close();
    startApp();
  });

  document.getElementById("btn-change-key").addEventListener("click", () => {
    disconnectWs();
    sessionStorage.removeItem(API_KEY_STORAGE);
    apiKey = "";
    document.getElementById("main-content").hidden = true;
    document.getElementById("btn-change-key").hidden = true;
    showAuthDialog();
  });

  document.getElementById("btn-refresh-agents").addEventListener("click", () =>
    refreshAgents()
  );
  document.getElementById("btn-refresh-state").addEventListener("click", () =>
    refreshState()
  );
  document.getElementById("btn-clear-events").addEventListener("click", () => {
    document.getElementById("event-log").textContent = "";
  });
  document.getElementById("btn-fire-camera-motion").addEventListener("click", () =>
    fireCameraMotion()
  );

  document.querySelectorAll(".hook-preset-btn").forEach((btn) => {
    btn.addEventListener("click", () => applyHookPreset(btn.dataset.preset));
  });
  document.querySelectorAll(".cursor-hook-preset-btn").forEach((btn) => {
    btn.addEventListener("click", () => applyCursorHookPreset(btn.dataset.preset));
  });
  document.getElementById("btn-send-hook").addEventListener("click", () => sendHook());
  document.getElementById("btn-send-cursor-hook").addEventListener("click", () => sendCursorHook());
}

function showAuthDialog() {
  const dialog = document.getElementById("auth-dialog");
  dialog.showModal();
  document.getElementById("api-key-input").focus();
}

async function loadActionSchema() {
  try {
    const res = await fetch("action-settings.json");
    if (res.ok) {
      actionSchema = await res.json();
      return;
    }
  } catch {
    /* fallback below */
  }
  actionSchema = fallbackActionSchema();
}

function fallbackActionSchema() {
  return {
    [UUID.AGENT_STATUS]: {
      label: "Agent Status",
      fields: {
        agent_id: { type: "string", discovery: "agents", default: "" },
        default_input: { type: "string", default: "" },
        sounds_enabled: { type: "boolean", default: true },
        auto_retry: { type: "boolean", default: false },
        retry_max: { type: "integer", enum: [1, 2, 3, 5], default: 3 },
      },
    },
    [UUID.WIDGET]: {
      label: "Data Widget",
      fields: {
        state_key: { type: "string", default: "" },
        display_format: { type: "enum", values: ["raw", "boolean", "number", "currency", "percentage"], default: "raw" },
        action_on_press: { type: "string", default: "" },
      },
    },
    [UUID.SIGNAL]: {
      label: "Signal Trigger",
      fields: {
        signal_name: { type: "string", default: "" },
        signal_payload: { type: "json", default: "" },
      },
    },
    [UUID.ACTION_RUN]: {
      label: "Run Action",
      fields: {
        action_name: { type: "string", default: "" },
        action_payload: { type: "json", default: "" },
      },
    },
    [UUID.DASHBOARD]: {
      label: "Agent Dashboard",
      fields: {
        agent_filter: { type: "string", default: "*" },
        default_input: { type: "string", default: "" },
      },
    },
    [UUID.AGENT_SLOT]: {
      label: "Agent Slot",
      fields: {
        slot_index: { type: "integer", enum: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15], default: 1 },
        agent_filter: { type: "string", default: "cursor" },
        page: { type: "integer", enum: [1, 2], default: 1 },
        default_input: { type: "string", default: "" },
        sounds_enabled: { type: "boolean", default: true },
      },
    },
  };
}

async function startApp() {
  document.getElementById("main-content").hidden = false;
  document.getElementById("btn-change-key").hidden = false;
  await loadActionSchema();
  initHookBuilder();
  try {
    await refreshHealth();
    await Promise.all([refreshAgents(), refreshState(), refreshActions(), refreshSignals()]);
    initVirtualTiles();
    connectWs();
  } catch (err) {
    logEvent("error", `Startup failed: ${err.message}`);
    setHealthBadge(false, err.message);
  }
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

async function api(method, path, body) {
  const opts = {
    method,
    headers: {
      Authorization: `Bearer ${apiKey}`,
      Accept: "application/json",
    },
  };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const err = await res.json();
      detail = err.detail || JSON.stringify(err);
    } catch {
      /* ignore */
    }
    throw new Error(`${method} ${path}: ${detail}`);
  }
  if (res.status === 204) return null;
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) return res.json();
  return null;
}

async function refreshHealth() {
  try {
    const data = await fetch("/health").then((r) => r.json());
    setHealthBadge(true, `v${data.version} · ${data.agents?.count ?? 0} agents`);
  } catch (err) {
    setHealthBadge(false, err.message);
    throw err;
  }
}

function setHealthBadge(ok, text) {
  const el = document.getElementById("health-status");
  el.textContent = `Health: ${text}`;
  el.className = `badge ${ok ? "badge-ok" : "badge-error"}`;
}

async function refreshAgents() {
  agents = await api("GET", "/agents");
  const ids = agents
    .map((a) => a.id)
    .sort()
    .join(",");
  if (ids !== lastAgentIds) {
    lastAgentIds = ids;
    rebuildVirtualTiles();
  } else {
    updateVirtualTiles();
  }
  renderAgentsTable();
}

async function refreshState() {
  stateEntries = await api("GET", "/state");
  stateByKey.clear();
  for (const e of stateEntries) {
    stateByKey.set(e.key, e);
  }
  const keys = stateEntries
    .map((e) => e.key)
    .sort()
    .join(",");
  if (keys !== lastStateKeys) {
    lastStateKeys = keys;
    rebuildVirtualTiles();
  } else {
    updateVirtualTiles();
  }
  renderStateTable();
}

async function refreshActions() {
  const data = await api("GET", "/actions");
  actionsList = data.actions || [];
  renderActionsPanel(actionsList);
  rebuildVirtualTiles();
}

async function refreshSignals() {
  const data = await api("GET", "/signals");
  signalsList = data.signals || [];
  const names = signalsList
    .map((s) => s.name)
    .sort()
    .join(",");
  if (names !== lastSignalNames) {
    lastSignalNames = names;
    rebuildVirtualTiles();
  }
  renderSignalsPanel(signalsList);
}

async function fireCameraMotion() {
  await api("POST", "/signals/webhook/camera.motion", {
    key: "camera.front_door.motion",
    active: true,
    ttl_seconds: 30,
  });
  logEvent("signal", "Fired camera.motion");
}

// ---------------------------------------------------------------------------
// Agents UI
// ---------------------------------------------------------------------------

function renderAgentsTable() {
  const wrap = document.getElementById("agents-table");
  if (!agents.length) {
    wrap.innerHTML = '<p class="empty">No agents registered.</p>';
    return;
  }

  const rows = agents
    .map((agent) => {
      const status = agent.status || "idle";
      const primary = primaryAgentAction(agent);
      const inputField =
        status === "awaiting_input"
          ? `<input type="text" class="agent-input" data-agent-id="${escapeAttr(agent.id)}" placeholder="Input text" />`
          : "";
      return `<tr data-agent-id="${escapeAttr(agent.id)}">
        <td><strong>${escapeHtml(agent.id)}</strong><br><span class="hint">${escapeHtml(agent.display_label || agent.type || "")}</span></td>
        <td><span class="status-pill status-${status}">${escapeHtml(status)}</span></td>
        <td class="agent-actions">
          <button type="button" class="btn btn-primary agent-action-btn" data-agent-id="${escapeAttr(agent.id)}">${escapeHtml(primary.label)}</button>
          ${inputField}
        </td>
      </tr>`;
    })
    .join("");

  wrap.innerHTML = `<table>
    <thead><tr><th>Agent</th><th>Status</th><th>Actions</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>`;

  wrap.querySelectorAll(".agent-action-btn").forEach((btn) => {
    btn.addEventListener("click", () => onAgentAction(btn.dataset.agentId));
  });
}

function primaryAgentAction(agent) {
  const status = agent.status || "idle";
  if (status === "idle") return { label: "Start", action: "start" };
  if (status === "running") return { label: "Cancel", action: "cancel" };
  if (status === "awaiting_input") return { label: "Send input", action: "input" };
  if (status === "error") return { label: "Restart", action: "start" };
  return { label: "Start", action: "start" };
}

async function onAgentAction(agentId, options = {}) {
  const agent = agents.find((a) => a.id === agentId);
  if (!agent) return;
  const status = agent.status || "idle";
  const defaultInput = options.defaultInput ?? "";
  try {
    if (status === "running") {
      await api("POST", `/agents/${encodeURIComponent(agentId)}/cancel`);
    } else if (status === "awaiting_input") {
      const row = document.querySelector(`tr[data-agent-id="${CSS.escape(agentId)}"]`);
      const input = row?.querySelector(".agent-input");
      const text = input?.value?.trim() || defaultInput || "hello";
      await api("POST", `/agents/${encodeURIComponent(agentId)}/input`, { text });
    } else {
      if (status === "error" && options.resetRetry) {
        clearTileRetryForAgent(agentId);
      }
      await api("POST", `/agents/${encodeURIComponent(agentId)}/start`);
    }
    await refreshAgents();
  } catch (err) {
    logEvent("error", err.message);
  }
}

function renderActionsPanel(actions) {
  const panel = document.getElementById("actions-panel");
  if (!actions.length) {
    panel.innerHTML = '<p class="empty">No actions registered.</p>';
    return;
  }
  panel.innerHTML = actions
    .map(
      (a) => `<div class="action-row" data-action="${escapeAttr(a.name)}">
        <label>Name<br><strong>${escapeHtml(a.name)}</strong></label>
        <label>Payload (JSON)<br><textarea class="action-payload" rows="2">{}</textarea></label>
        <button type="button" class="btn btn-primary run-action-btn">Run</button>
      </div>`
    )
    .join("");

  panel.querySelectorAll(".run-action-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const row = btn.closest(".action-row");
      const name = row.dataset.action;
      const payloadText = row.querySelector(".action-payload").value;
      try {
        const payload = JSON.parse(payloadText || "{}");
        await api("POST", `/actions/${encodeURIComponent(name)}`, payload);
        logEvent("action", `Ran ${name}`);
        await refreshAgents();
        await refreshState();
      } catch (err) {
        logEvent("error", err.message);
      }
    });
  });
}

function renderSignalsPanel(signals) {
  const panel = document.getElementById("signals-panel");
  if (!signals.length) {
    panel.innerHTML = '<p class="empty">No signals registered.</p>';
    return;
  }
  panel.innerHTML = signals
    .map(
      (s) => `<div class="signal-row" data-signal="${escapeAttr(s.name)}">
        <label>Name<br><strong>${escapeHtml(s.name)}</strong></label>
        <label>Payload (JSON)<br><textarea class="signal-payload" rows="2">{}</textarea></label>
        <button type="button" class="btn btn-primary run-signal-btn">Fire</button>
      </div>`
    )
    .join("");

  panel.querySelectorAll(".run-signal-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const row = btn.closest(".signal-row");
      const name = row.dataset.signal;
      const payloadText = row.querySelector(".signal-payload").value;
      try {
        const payload = JSON.parse(payloadText || "{}");
        await api("POST", `/signals/webhook/${encodeURIComponent(name)}`, payload);
        logEvent("signal", `Fired ${name}`);
        await refreshState();
      } catch (err) {
        logEvent("error", err.message);
      }
    });
  });
}

// ---------------------------------------------------------------------------
// State UI
// ---------------------------------------------------------------------------

function renderStateTable() {
  const wrap = document.getElementById("state-table");
  if (!stateEntries.length) {
    wrap.innerHTML = '<p class="empty">No state keys.</p>';
    return;
  }
  const rows = stateEntries
    .map((e) => {
      const expires = e.expires_at
        ? new Date(e.expires_at * 1000).toLocaleTimeString()
        : "—";
      return `<tr data-state-key="${escapeAttr(e.key)}">
        <td><code>${escapeHtml(e.key)}</code></td>
        <td><pre style="margin:0;font-size:0.75rem">${escapeHtml(JSON.stringify(e.value, null, 0))}</pre></td>
        <td>${expires}</td>
      </tr>`;
    })
    .join("");
  wrap.innerHTML = `<table>
    <thead><tr><th>Key</th><th>Value</th><th>Expires</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

function flashStateRow(key) {
  const row = document.querySelector(`tr[data-state-key="${CSS.escape(key)}"]`);
  if (!row) return;
  row.classList.remove("state-flash");
  void row.offsetWidth;
  row.classList.add("state-flash");
}

// ---------------------------------------------------------------------------
// Virtual tiles (v2)
// ---------------------------------------------------------------------------

function defaultSettingsForUuid(actionUuid) {
  const def = actionSchema[actionUuid]?.fields || {};
  const settings = {};
  for (const [key, meta] of Object.entries(def)) {
    settings[key] = meta.default ?? "";
  }
  return settings;
}

function defaultSlots() {
  const presets = [
    { action_uuid: UUID.DASHBOARD, settings: { agent_filter: "cursor" } },
    { action_uuid: UUID.AGENT_SLOT, settings: { slot_index: 1, agent_filter: "cursor", page: 1 } },
    { action_uuid: UUID.AGENT_SLOT, settings: { slot_index: 2, agent_filter: "cursor", page: 1 } },
    { action_uuid: UUID.AGENT_SLOT, settings: { slot_index: 3, agent_filter: "cursor", page: 1 } },
    { action_uuid: UUID.WIDGET, settings: { state_key: "cursor.summary", display_format: "summary" } },
    { action_uuid: UUID.AGENT_STATUS, settings: { agent_id: "mock-1", default_input: "hello" } },
  ];
  return presets.map((p) => normalizeSlot(p));
}

function normalizeSlot(slot) {
  const actionUuid = slot.action_uuid || UUID.AGENT_STATUS;
  const base = defaultSettingsForUuid(actionUuid);
  const merged = { ...base, ...(slot.settings || {}) };
  const fields = actionSchema[actionUuid]?.fields || {};
  for (const [key, meta] of Object.entries(fields)) {
    if (meta.type === "boolean") {
      merged[key] = merged[key] !== false && merged[key] !== "false";
    }
    if (meta.type === "integer" && key in merged) {
      merged[key] = Number(merged[key]) || meta.default || 3;
    }
  }
  return { action_uuid: actionUuid, settings: merged };
}

function migrateV1Tile(tile) {
  const kind = tile.kind === "widget" ? "widget" : "agent";
  if (kind === "widget") {
    return normalizeSlot({
      action_uuid: UUID.WIDGET,
      settings: {
        state_key: tile.state_key || "",
        display_format: tile.display_format || "raw",
        action_on_press: tile.action_on_press ?? "",
      },
    });
  }
  return normalizeSlot({
    action_uuid: UUID.AGENT_STATUS,
    settings: {
      agent_id: tile.agent_id || "",
      default_input: tile.default_input ?? "",
      sounds_enabled: tile.sounds_enabled !== false,
      auto_retry: Boolean(tile.auto_retry),
      retry_max: Number(tile.retry_max) || 3,
    },
  });
}

function loadTiles() {
  try {
    const rawV2 = localStorage.getItem(TILES_STORAGE_V2);
    if (rawV2) {
      const parsed = JSON.parse(rawV2);
      const slots = parsed.slots || parsed;
      if (Array.isArray(slots) && slots.length === TILE_COUNT) {
        return slots.map(normalizeSlot);
      }
    }
    const rawV1 = localStorage.getItem(TILES_STORAGE_V1);
    if (rawV1) {
      const parsed = JSON.parse(rawV1);
      if (Array.isArray(parsed) && parsed.length === TILE_COUNT) {
        const migrated = parsed.map(migrateV1Tile);
        saveTiles(migrated);
        return migrated;
      }
    }
  } catch {
    /* ignore */
  }
  const defaults = defaultSlots();
  saveTiles(defaults);
  return defaults;
}

function saveTiles(slots) {
  localStorage.setItem(
    TILES_STORAGE_V2,
    JSON.stringify({ version: 2, slots: slots.map(normalizeSlot) })
  );
}

function initVirtualTiles() {
  rebuildVirtualTiles();
}

function rebuildVirtualTiles() {
  const container = document.getElementById("virtual-tiles");
  const slots = loadTiles();
  container.innerHTML = "";

  slots.forEach((slot, index) => {
    const el = document.createElement("div");
    el.className = "virtual-tile tile-neutral";
    el.dataset.index = String(index);
    el.innerHTML = buildTileInner(slot, index);
    container.appendChild(el);
    bindTileElement(el, index);
  });

  updateVirtualTiles();
}

function actionTypeOptions(selectedUuid) {
  return Object.entries(actionSchema)
    .map(
      ([uuid, meta]) =>
        `<option value="${escapeAttr(uuid)}" ${uuid === selectedUuid ? "selected" : ""}>${escapeHtml(meta.label || uuid)}</option>`
    )
    .join("");
}

function buildFieldHtml(fieldKey, meta, value, index) {
  const id = `tile-${index}-${fieldKey}`;
  const label = fieldKey.replace(/_/g, " ");

  if (meta.type === "boolean") {
    const checked = value !== false;
    return `<label class="inline"><input type="checkbox" class="tile-field" data-field="${escapeAttr(fieldKey)}" ${checked ? "checked" : ""} /> ${escapeHtml(label)}</label>`;
  }

  if (meta.type === "enum") {
    const opts = (meta.values || [])
      .map(
        (v) =>
          `<option value="${escapeAttr(v)}" ${value === v ? "selected" : ""}>${escapeHtml(v)}</option>`
      )
      .join("");
    return `<label>${escapeHtml(label)}<select class="tile-field" data-field="${escapeAttr(fieldKey)}">${opts}</select></label>`;
  }

  if (meta.type === "integer" && meta.enum) {
    const opts = meta.enum
      .map(
        (n) =>
          `<option value="${n}" ${Number(value) === n ? "selected" : ""}>${n}</option>`
      )
      .join("");
    return `<label>${escapeHtml(label)}<select class="tile-field" data-field="${escapeAttr(fieldKey)}">${opts}</select></label>`;
  }

  if (meta.type === "json") {
    return `<label>${escapeHtml(label)}<textarea class="tile-field tile-json" data-field="${escapeAttr(fieldKey)}" rows="2" spellcheck="false">${escapeHtml(String(value ?? ""))}</textarea></label>`;
  }

  if (meta.discovery === "agents") {
    const opts = agents
      .map(
        (a) =>
          `<option value="${escapeAttr(a.id)}" ${value === a.id ? "selected" : ""}>${escapeHtml(a.id)}</option>`
      )
      .join("");
    return `<label>${escapeHtml(label)}<select class="tile-field" data-field="${escapeAttr(fieldKey)}"><option value="">—</option>${opts}</select></label>`;
  }

  if (meta.discovery === "signals") {
    const opts = signalsList
      .map(
        (s) =>
          `<option value="${escapeAttr(s.name)}" ${value === s.name ? "selected" : ""}>${escapeHtml(s.name)}</option>`
      )
      .join("");
    return `<label>${escapeHtml(label)}<select class="tile-field" data-field="${escapeAttr(fieldKey)}"><option value="">—</option>${opts}</select></label>`;
  }

  if (meta.discovery === "actions") {
    const datalistId = `tile-actions-${index}-${fieldKey}`;
    const opts = actionsList.map((a) => `<option value="${escapeAttr(a.name)}"></option>`).join("");
    return `<label>${escapeHtml(label)}
      <input type="text" class="tile-field" data-field="${escapeAttr(fieldKey)}" list="${datalistId}" value="${escapeAttr(value ?? "")}" />
      <datalist id="${datalistId}">${opts}</datalist>
    </label>`;
  }

  if (meta.discovery === "state_keys") {
    const datalistId = `tile-state-keys-${index}`;
    const opts = stateEntries.map((e) => `<option value="${escapeAttr(e.key)}"></option>`).join("");
    return `<label>${escapeHtml(label)}
      <input type="text" class="tile-field" data-field="${escapeAttr(fieldKey)}" list="${datalistId}" value="${escapeAttr(value ?? "")}" placeholder="camera.front_door.motion" />
      <datalist id="${datalistId}">${opts}</datalist>
    </label>`;
  }

  return `<label>${escapeHtml(label)}<input type="text" class="tile-field" data-field="${escapeAttr(fieldKey)}" value="${escapeAttr(value ?? "")}" /></label>`;
}

function buildTileInner(slot, index) {
  const fields = actionSchema[slot.action_uuid]?.fields || {};
  const settingsHtml = Object.entries(fields)
    .map(([key, meta]) => buildFieldHtml(key, meta, slot.settings[key], index))
    .join("");

  return `
    <div class="tile-face">
      <div class="tile-title">—</div>
      <div class="tile-sub">slot ${index + 1}</div>
      <span class="tile-sound-badge" hidden>🔊</span>
    </div>
    <details class="tile-settings">
      <summary>Settings</summary>
      <label>Action<select class="tile-action-uuid">${actionTypeOptions(slot.action_uuid)}</select></label>
      <p class="tile-uuid-hint hint">${escapeHtml(slot.action_uuid)}</p>
      <div class="tile-settings-body">${settingsHtml || '<p class="hint">No settings for this action.</p>'}</div>
    </details>`;
}

function bindTileElement(el, index) {
  const face = el.querySelector(".tile-face");
  face?.addEventListener("click", () => onVirtualTilePress(index));

  el.querySelectorAll(".tile-field, .tile-action-uuid").forEach((ctrl) => {
    const event =
      ctrl.tagName === "SELECT" || ctrl.type === "checkbox" ? "change" : "input";
    ctrl.addEventListener(event, () => onTileConfigChange(index, el));
    ctrl.addEventListener("click", (ev) => ev.stopPropagation());
  });

  el.querySelector(".tile-action-uuid")?.addEventListener("change", () => {
    const uuid = el.querySelector(".tile-action-uuid").value;
    const slots = loadTiles();
    slots[index] = normalizeSlot({ action_uuid: uuid, settings: {} });
    saveTiles(slots);
    rebuildVirtualTiles();
  });
}

function readSlotFromEl(el) {
  const actionUuid = el.querySelector(".tile-action-uuid")?.value || UUID.AGENT_STATUS;
  const settings = defaultSettingsForUuid(actionUuid);
  const fields = actionSchema[actionUuid]?.fields || {};

  el.querySelectorAll(".tile-field").forEach((ctrl) => {
    const key = ctrl.dataset.field;
    if (!key) return;
    const meta = fields[key] || {};
    if (meta.type === "boolean") {
      settings[key] = ctrl.checked;
    } else if (meta.type === "integer") {
      settings[key] = parseInt(ctrl.value, 10) || meta.default || 3;
    } else if (meta.type === "json") {
      settings[key] = ctrl.value ?? "";
    } else {
      settings[key] = ctrl.value ?? "";
    }
  });

  return normalizeSlot({ action_uuid: actionUuid, settings });
}

function onTileConfigChange(index, el) {
  const slots = loadTiles();
  slots[index] = readSlotFromEl(el);
  saveTiles(slots);
  updateVirtualTiles();
}

function getFlashTitle(index) {
  const flash = tileFlashState.get(index);
  if (flash && Date.now() < flash.until) return flash.title;
  if (flash) tileFlashState.delete(index);
  return null;
}

function setTileFlash(index, title, ms, onDone) {
  tileFlashState.set(index, { title, until: Date.now() + ms });
  updateVirtualTiles();
  setTimeout(() => {
    const f = tileFlashState.get(index);
    if (!f) return;
    tileFlashState.delete(index);
    updateVirtualTiles();
    onDone?.();
  }, ms);
}

function applyTileFace(el, index, slot, title, sub, statusClass) {
  const titleEl = el.querySelector(".tile-title");
  const subEl = el.querySelector(".tile-sub");
  const flash = getFlashTitle(index);
  const retry = tileRetryState.get(index);

  el.className = "virtual-tile";
  if (statusClass) el.classList.add(statusClass);
  else el.classList.add("tile-neutral");
  el.classList.remove("tile-running-active");

  if (flash) {
    el.classList.add("tile-flash");
    titleEl.textContent = flash.title;
    subEl.textContent = sub;
    return;
  }
  el.classList.remove("tile-flash");

  if (retry?.pendingLabel) {
    titleEl.textContent = retry.pendingLabel;
    subEl.textContent = sub;
    return;
  }

  titleEl.textContent = title;
  subEl.textContent = sub;
}

function updateVirtualTiles() {
  const container = document.getElementById("virtual-tiles");
  const slots = loadTiles();
  const behavior = TB();

  container.querySelectorAll(".virtual-tile").forEach((el, index) => {
    const slot = slots[index];
    const s = slot.settings;
    const uuid = slot.action_uuid;

    if (uuid === UUID.AGENT_STATUS) {
      const agentId = s.agent_id;
      if (!agentId) {
        applyTileFace(el, index, slot, "No Agent", "configure below", "status-idle");
        return;
      }
      const agent = agents.find((a) => a.id === agentId);
      if (!agent) {
        applyTileFace(el, index, slot, agentId, "not found", "status-error");
        return;
      }
      const status = agent.status || "idle";
      const title = behavior.agentStatusTitle(agent, status);
      applyTileFace(el, index, slot, title, status, `status-${status}`);
      const soundBadge = el.querySelector(".tile-sound-badge");
      if (soundBadge) {
        soundBadge.hidden = !(s.sounds_enabled && status === "awaiting_input");
      }
      return;
    }

    if (uuid === UUID.WIDGET) {
      const face = behavior.widgetFaceTitle(s.state_key, stateByKey.get(s.state_key), s.display_format || "raw");
      applyTileFace(el, index, slot, face.title, face.sub, null);
      return;
    }

    if (uuid === UUID.SIGNAL) {
      const title = behavior.signalIdleTitle(s.signal_name);
      applyTileFace(el, index, slot, title, "signal", null);
      return;
    }

    if (uuid === UUID.ACTION_RUN) {
      const title = behavior.actionRunIdleTitle(s.action_name);
      applyTileFace(el, index, slot, title, "action", null);
      return;
    }

    if (uuid === UUID.DASHBOARD) {
      const filter = s.agent_filter || "*";
      const title = agents.length
        ? behavior.buildFilteredDashboardTitle(agents, filter)
        : "No Agents";
      applyTileFace(el, index, slot, title, filter === "*" ? "dashboard" : filter, "tile-dashboard");
      return;
    }

    if (uuid === UUID.AGENT_SLOT) {
      const agent = behavior.agentForSlot(agents, Number(s.slot_index) || 1, {
        page: Number(s.page) || 1,
        agentFilter: s.agent_filter || "cursor",
      });
      if (!agent) {
        applyTileFace(el, index, slot, "—", `slot ${s.slot_index}`, "tile-neutral");
        return;
      }
      const status = agent.status || "idle";
      const title = behavior.agentSlotTitle(agent, status);
      applyTileFace(el, index, slot, title, `slot ${s.slot_index}`, `status-${status}`);
      if (status === "running") {
        el.classList.add("tile-running-active");
      }
      const soundBadge = el.querySelector(".tile-sound-badge");
      if (soundBadge) {
        soundBadge.hidden = !(s.sounds_enabled && status === "awaiting_input");
      }
      return;
    }

    applyTileFace(el, index, slot, "Unknown", uuid, null);
  });
}

async function onVirtualTilePress(index) {
  const slots = loadTiles();
  const slot = slots[index];
  const s = slot.settings;
  const behavior = TB();

  try {
    if (slot.action_uuid === UUID.AGENT_STATUS) {
      const agent = agents.find((a) => a.id === s.agent_id);
      if (!agent) return;
      await onAgentAction(agent.id, {
        defaultInput: s.default_input,
        resetRetry: (agent.status || "idle") === "error",
      });
      return;
    }

    if (slot.action_uuid === UUID.WIDGET) {
      if (!s.action_on_press) return;
      await api("POST", `/actions/${encodeURIComponent(s.action_on_press)}`, {});
      logEvent("action", `Tile ${index + 1}: ${s.action_on_press}`);
      await refreshAgents();
      await refreshState();
      return;
    }

    if (slot.action_uuid === UUID.SIGNAL) {
      if (!s.signal_name) return;
      const payload = behavior.parseJsonPayload(s.signal_payload);
      await api("POST", `/signals/webhook/${encodeURIComponent(s.signal_name)}`, payload);
      setTileFlash(index, "Sent!", TILE_FLASH_MS, () => {});
      logEvent("signal", `Tile ${index + 1}: ${s.signal_name}`);
      await refreshState();
      return;
    }

    if (slot.action_uuid === UUID.ACTION_RUN) {
      if (!s.action_name) return;
      const payload = behavior.parseJsonPayload(s.action_payload);
      await api("POST", `/actions/${encodeURIComponent(s.action_name)}`, payload);
      setTileFlash(index, "OK!", TILE_FLASH_MS, () => {});
      logEvent("action", `Tile ${index + 1}: ${s.action_name}`);
      await refreshAgents();
      await refreshState();
      return;
    }

    if (slot.action_uuid === UUID.DASHBOARD) {
      const filter = s.agent_filter || "*";
      if (behavior.needsAttention(agents, filter)) {
        const top = behavior.topAttentionAgent(agents, filter);
        if (top && (top.type === "cursor" || top.type === "cursor_cloud")) {
          await api("POST", "/actions/ui.focus_cursor_agent", { agent_id: top.id });
          logEvent("action", `Dashboard focus ${top.id}`);
          return;
        }
        if (top) {
          await onAgentAction(top.id, { defaultInput: s.default_input || "" });
          return;
        }
      }
      await refreshAgents();
      return;
    }

    if (slot.action_uuid === UUID.AGENT_SLOT) {
      const agent = behavior.agentForSlot(agents, Number(s.slot_index) || 1, {
        page: Number(s.page) || 1,
        agentFilter: s.agent_filter || "cursor",
      });
      if (!agent) return;
      const status = agent.status || "idle";
      if (agent.type === "cursor" || agent.type === "cursor_cloud") {
        await api("POST", "/actions/ui.focus_cursor_agent", { agent_id: agent.id });
        logEvent("action", `Slot ${s.slot_index} focus ${agent.id}`);
        return;
      }
      await onAgentAction(agent.id, {
        defaultInput: s.default_input,
        resetRetry: status === "error",
      });
      return;
    }
  } catch (err) {
    logEvent("error", err.message);
    if (slot.action_uuid === UUID.SIGNAL || slot.action_uuid === UUID.ACTION_RUN) {
      setTileFlash(index, "Error", TILE_FLASH_MS, () => {});
    }
  }
}

// ---------------------------------------------------------------------------
// Tile auto-retry (Agent Status)
// ---------------------------------------------------------------------------

function clearTileRetry(index) {
  const state = tileRetryState.get(index);
  if (state?.timer) clearTimeout(state.timer);
  tileRetryState.delete(index);
}

function clearTileRetryForAgent(agentId) {
  const slots = loadTiles();
  slots.forEach((slot, index) => {
    if (slot.action_uuid === UUID.AGENT_STATUS && slot.settings.agent_id === agentId) {
      clearTileRetry(index);
    }
  });
}

function scheduleTileRetry(index, agentId, slot) {
  clearTileRetry(index);
  const s = slot.settings;
  const state = { count: 0, timer: null, pendingLabel: null };
  const max = Number(s.retry_max) || 3;

  function attemptSchedule() {
    const nextAttempt = state.count + 1;
    if (nextAttempt > max) return;

    state.pendingLabel = `Retry ${nextAttempt}`;
    tileRetryState.set(index, state);
    updateVirtualTiles();

    const delay = TILE_RETRY_BASE_MS * nextAttempt;
    state.timer = window.setTimeout(async () => {
      state.timer = null;
      state.pendingLabel = null;
      state.count = nextAttempt;
      try {
        logEvent("retry", `Tile ${index + 1}: auto-retry ${nextAttempt}/${max} for ${agentId}`);
        await api("POST", `/agents/${encodeURIComponent(agentId)}/start`);
        await refreshAgents();
      } catch (err) {
        logEvent("error", err.message);
        if (state.count < max) attemptSchedule();
      }
      tileRetryState.set(index, state);
      updateVirtualTiles();
    }, delay);
    tileRetryState.set(index, state);
  }

  attemptSchedule();
}

function handleTileAutoRetry(agentId, newStatus) {
  const slots = loadTiles();
  slots.forEach((slot, index) => {
    if (slot.action_uuid !== UUID.AGENT_STATUS || slot.settings.agent_id !== agentId) return;
    if (newStatus === "error" && slot.settings.auto_retry) {
      scheduleTileRetry(index, agentId, slot);
    } else if (newStatus !== "error") {
      clearTileRetry(index);
    }
  });
}

// ---------------------------------------------------------------------------
// Claude Code hook builder
// ---------------------------------------------------------------------------

function initHookBuilder() {
  const textarea = document.getElementById("hook-payload");
  if (!textarea.value.trim()) {
    applyHookPreset("SessionStart");
  }
  const cursorTextarea = document.getElementById("cursor-hook-payload");
  if (cursorTextarea && !cursorTextarea.value.trim()) {
    applyCursorHookPreset("sessionStart");
  }
}

function applyHookPreset(name) {
  const preset = HOOK_PRESETS[name];
  if (!preset) return;
  document.getElementById("hook-payload").value = JSON.stringify(preset, null, 2);
}

async function sendHook() {
  const textarea = document.getElementById("hook-payload");
  const resultEl = document.getElementById("hook-result");
  try {
    const payload = JSON.parse(textarea.value);
    if (!payload.session_id || !payload.hook_event_name) {
      throw new Error("Payload requires session_id and hook_event_name");
    }
    const res = await api("POST", "/agents/claude-code/hook", payload);
    const agentId = res.agent?.id || res.agent_id || "—";
    resultEl.textContent = `${res.status} → ${agentId}`;
    logEvent("hook", `${payload.hook_event_name} → ${agentId}`);
    await refreshAgents();
    await refreshState();
  } catch (err) {
    resultEl.textContent = err.message;
    logEvent("error", err.message);
  }
}

function applyCursorHookPreset(name) {
  const preset = CURSOR_HOOK_PRESETS[name];
  if (!preset) return;
  document.getElementById("cursor-hook-payload").value = JSON.stringify(preset, null, 2);
}

async function sendCursorHook() {
  const textarea = document.getElementById("cursor-hook-payload");
  const resultEl = document.getElementById("cursor-hook-result");
  try {
    const payload = JSON.parse(textarea.value);
    if (!payload.session_id || !payload.hook_event_name) {
      throw new Error("Payload requires session_id and hook_event_name");
    }
    const res = await api("POST", "/agents/cursor/hook", payload);
    const agentId = res.agent?.id || res.agent_id || "—";
    resultEl.textContent = `${res.status} → ${agentId}`;
    logEvent("hook", `cursor:${payload.hook_event_name} → ${agentId}`);
    await refreshAgents();
    await refreshState();
  } catch (err) {
    resultEl.textContent = err.message;
    logEvent("error", err.message);
  }
}

// ---------------------------------------------------------------------------
// WebSocket
// ---------------------------------------------------------------------------

function connectWs() {
  disconnectWs();
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const url = `${proto}//${location.host}/events`;
  ws = new WebSocket(url);

  ws.addEventListener("open", () => {
    ws.send(JSON.stringify({ type: "auth", token: apiKey }));
  });

  ws.addEventListener("message", async (ev) => {
    let msg;
    try {
      msg = JSON.parse(ev.data);
    } catch {
      return;
    }
    if (msg.type === "auth_ok") {
      setWsBadge(true, `connected (${msg.scope})`);
      return;
    }
    if (msg.type === "auth_error") {
      setWsBadge(false, msg.detail || "auth failed");
      return;
    }
    handleEvent(msg);
  });

  ws.addEventListener("close", () => {
    setWsBadge(false, "disconnected");
    scheduleWsReconnect();
  });

  ws.addEventListener("error", () => {
    setWsBadge(false, "error");
  });
}

function disconnectWs() {
  if (wsReconnectTimer) {
    clearTimeout(wsReconnectTimer);
    wsReconnectTimer = null;
  }
  if (ws) {
    ws.close();
    ws = null;
  }
}

function scheduleWsReconnect() {
  if (wsReconnectTimer) return;
  wsReconnectTimer = setTimeout(() => {
    wsReconnectTimer = null;
    if (apiKey) connectWs();
  }, 3000);
}

function setWsBadge(ok, text) {
  const el = document.getElementById("ws-status");
  el.textContent = `Events: ${text}`;
  el.className = `badge ${ok ? "badge-ok" : ok === false ? "badge-error" : "badge-muted"}`;
}

async function handleEvent(event) {
  logEvent(event.type, JSON.stringify(event.payload ?? {}));
  const type = event.type;
  const payload = event.payload || {};

  if (type === "agent.status_changed" || type === "agent.context_changed") {
    const agentData = payload.agent || {};
    const agentId = agentData.id || payload.agent_id || "";
    const newStatus = agentData.status || payload.status || "";
    if (type === "agent.status_changed" && agentId) {
      handleTileAutoRetry(agentId, newStatus);
    }
    await refreshAgents();
    updateVirtualTiles();
  }
  if (type === "agent.registered" || type === "agent.unregistered") {
    await refreshAgents();
    await refreshState();
    updateVirtualTiles();
  }
  if (type === "state.changed") {
    const key = payload.key;
    const entry = {
      key,
      value: payload.value,
      updated_at: event.ts,
      expires_at: payload.expires_at,
    };
    stateByKey.set(key, entry);
    const idx = stateEntries.findIndex((e) => e.key === key);
    if (idx >= 0) stateEntries[idx] = entry;
    else stateEntries.push(entry);
    renderStateTable();
    flashStateRow(key);
    updateVirtualTiles();
  }
  if (type === "state.cleared") {
    await refreshState();
  }
}

function logEvent(type, detail) {
  const log = document.getElementById("event-log");
  const ts = new Date().toLocaleTimeString();
  const line = document.createElement("div");
  line.className = "event-line";
  line.innerHTML = `<span class="ts">${escapeHtml(ts)}</span> <strong>${escapeHtml(type)}</strong> ${escapeHtml(detail)}`;
  log.prepend(line);
  while (log.children.length > MAX_EVENTS) {
    log.removeChild(log.lastChild);
  }
}

// ---------------------------------------------------------------------------
// Utils
// ---------------------------------------------------------------------------

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function escapeAttr(s) {
  return escapeHtml(s).replace(/'/g, "&#39;");
}
