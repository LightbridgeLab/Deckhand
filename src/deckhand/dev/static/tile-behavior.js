/**
 * Shared tile face helpers — parity with OpenDeck plugin action handlers.
 * @see opendeck-plugin/com.deckhand.plugin.sdPlugin/actions/
 */
(function (global) {
  const STATUS_TITLES = {
    idle: "",
    running: "Running",
    awaiting_input: "Input!",
    error: "Error",
  };

  const TRUTHY_BOOLEAN = [true, 1, "true", "True", "1", "yes", "on"];

  const DASHBOARD_STATUS_EMOJI = {
    idle: "-",
    running: ">",
    awaiting_input: "?",
    error: "!",
  };

  const STATUS_PRIORITY = {
    awaiting_input: 0,
    error: 1,
    running: 2,
    idle: 3,
  };

  const ATTENTION_STATUSES = new Set(["awaiting_input", "error"]);

  function matchesAgentFilter(agent, agentFilter) {
    if (!agentFilter || agentFilter === "*") return true;
    return agent.type === agentFilter;
  }

  function rankAgents(agents, agentFilter = "*") {
    const filtered = (agents || []).filter((a) => matchesAgentFilter(a, agentFilter));
    return filtered.slice().sort((a, b) => {
      const pa = STATUS_PRIORITY[a.status || "idle"] ?? 99;
      const pb = STATUS_PRIORITY[b.status || "idle"] ?? 99;
      if (pa !== pb) return pa - pb;
      return (b.updated_at || 0) - (a.updated_at || 0);
    });
  }

  function agentForSlot(agents, slotIndex, { page = 1, perPage = 7, agentFilter = "*" } = {}) {
    if (slotIndex < 1) return null;
    const ranked = rankAgents(agents, agentFilter);
    const offset = (Math.max(page, 1) - 1) * perPage + slotIndex - 1;
    return ranked[offset] || null;
  }

  function needsAttention(agents, agentFilter = "*") {
    return (agents || []).some(
      (a) => matchesAgentFilter(a, agentFilter) && ATTENTION_STATUSES.has(a.status || "idle")
    );
  }

  function topAttentionAgent(agents, agentFilter = "*") {
    const ranked = rankAgents(agents, agentFilter);
    if (!ranked.length) return null;
    return ranked.find((a) => ATTENTION_STATUSES.has(a.status || "idle")) || ranked[0];
  }

  function buildFilteredDashboardTitle(agents, agentFilter = "*") {
    return buildDashboardTitle((agents || []).filter((a) => matchesAgentFilter(a, agentFilter)));
  }

  function agentSlotTitle(agent, status) {
    if (!agent) return "—";
    return agentStatusTitle(agent, status);
  }

  function shortName(dotted) {
    if (!dotted) return "";
    const parts = String(dotted).split(".");
    return parts[parts.length - 1] || dotted;
  }

  function parseJsonPayload(str) {
    const raw = str == null ? "" : String(str).trim();
    if (!raw) return {};
    try {
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
    } catch {
      return {};
    }
  }

  function formatValue(value, fmt) {
    if (value !== null && typeof value === "object") {
      if (Object.keys(value).length === 1) {
        value = Object.values(value)[0];
      } else {
        return JSON.stringify(value).slice(0, 12);
      }
    }

    if (fmt === "summary" && value && typeof value === "object" && value.title) {
      return String(value.title).slice(0, 12);
    }

    if (fmt === "currency" && typeof value === "number") {
      return `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    }

    if (fmt === "percentage") {
      const num = Number(value);
      if (!Number.isNaN(num)) return `${Math.round(num)}%`;
    }

    if (fmt === "boolean") {
      const truthy = TRUTHY_BOOLEAN.includes(value);
      return truthy ? "\u2713" : "\u2717";
    }

    if (fmt === "number") {
      const num = Number(value);
      if (!Number.isNaN(num)) {
        return Number.isInteger(num) ? num.toLocaleString() : num.toFixed(2);
      }
    }

    return String(value ?? "—").slice(0, 12);
  }

  function agentStatusTitle(agent, status) {
    const label = agent.display_label || agent.id;
    if (status === "idle") return label;
    return STATUS_TITLES[status] || label;
  }

  function buildDashboardTitle(agents) {
    if (!agents || !agents.length) return "No Agents";
    const counts = {};
    for (const agent of agents) {
      const status = agent.status || "idle";
      counts[status] = (counts[status] || 0) + 1;
    }
    const parts = [];
    for (const status of ["running", "awaiting_input", "error", "idle"]) {
      const count = counts[status] || 0;
      if (count > 0) {
        parts.push(`${count}${DASHBOARD_STATUS_EMOJI[status] || ""}`);
      }
    }
    return parts.length ? parts.join(" ") : `${agents.length} agents`;
  }

  function widgetFaceTitle(stateKey, entry, displayFormat) {
    if (!stateKey) return { title: "No Key", sub: "configure below" };
    if (!entry) return { title: "—", sub: stateKey };
    return {
      title: formatValue(entry.value, displayFormat),
      sub: stateKey,
    };
  }

  function signalIdleTitle(signalName) {
    return signalName ? shortName(signalName) : "No Signal";
  }

  function actionRunIdleTitle(actionName) {
    return actionName ? shortName(actionName) : "No Action";
  }

  global.DeckhandTileBehavior = {
    STATUS_TITLES,
    shortName,
    parseJsonPayload,
    formatValue,
    agentStatusTitle,
    buildDashboardTitle,
    buildFilteredDashboardTitle,
    matchesAgentFilter,
    rankAgents,
    agentForSlot,
    needsAttention,
    topAttentionAgent,
    agentSlotTitle,
    widgetFaceTitle,
    signalIdleTitle,
    actionRunIdleTitle,
  };
})(typeof window !== "undefined" ? window : globalThis);
