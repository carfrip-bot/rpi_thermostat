"use strict";

const CONFIG_KEY = "rpiThermostatWebConfigV1";
const STATUS_TIMEOUT_SECONDS = 10;
const STATUS_POLL_MS = 1000;
const CONFIG_POLL_MS = 2500;
const DEFAULT_CONFIG = {
  revision: 0,
  updated_at: "1970-01-01T00:00:00+00:00",
  channels: {
    ch1: { setpoint: 20, hysteresis: 0.5, mode: "heating", enabled: true, schedule: [] },
    ch2: { setpoint: 20, hysteresis: 0.5, mode: "heating", enabled: true, schedule: [] },
  },
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const state = {
  db: null,
  config: null,
  status: null,
  statusOnline: false,
  databaseOnline: false,
  activeChannel: null,
  pendingRevision: null,
  pendingTimer: null,
  pollTimer: null,
  previousRelay: { CH1: null, CH2: null },
  updatingConfig: false,
};

class FirebaseRestClient {
  constructor({ apiKey, databaseUrl, expectedUid, email, password }) {
    this.apiKey = apiKey;
    this.databaseUrl = databaseUrl.replace(/\/+$/, "");
    this.expectedUid = expectedUid.trim();
    this.email = email.trim();
    this.password = password;
    this.idToken = null;
    this.refreshToken = null;
    this.expiresAt = 0;
  }

  async signIn() {
    const response = await this.fetchJson(
      `https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=${encodeURIComponent(this.apiKey)}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: this.email, password: this.password, returnSecureToken: true }),
      },
    );
    if (this.expectedUid && response.localId !== this.expectedUid) {
      throw new Error("L’UID dell’account autenticato non corrisponde a quello autorizzato.");
    }
    this.setTokens(response.idToken, response.refreshToken, response.expiresIn);
    this.password = "";
    return response;
  }

  setTokens(idToken, refreshToken, expiresIn) {
    this.idToken = idToken;
    this.refreshToken = refreshToken;
    this.expiresAt = Date.now() + Number(expiresIn || 3600) * 1000;
  }

  async ensureToken() {
    if (!this.idToken) throw new Error("Sessione Firebase scaduta. Accedi di nuovo.");
    if (Date.now() < this.expiresAt - 60_000) return;
    const body = new URLSearchParams({ grant_type: "refresh_token", refresh_token: this.refreshToken });
    const response = await this.fetchJson(
      `https://securetoken.googleapis.com/v1/token?key=${encodeURIComponent(this.apiKey)}`,
      { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body },
    );
    this.setTokens(response.id_token, response.refresh_token, response.expires_in);
  }

  async get(path) {
    return this.request("GET", path);
  }

  async put(path, value) {
    return this.request("PUT", path, value);
  }

  async request(method, path, value) {
    await this.ensureToken();
    const cleanPath = path.split("/").filter(Boolean).map(encodeURIComponent).join("/");
    const url = new URL(`${this.databaseUrl}/${cleanPath}.json`);
    url.searchParams.set("auth", this.idToken);
    if (method === "PUT") url.searchParams.set("print", "silent");
    const options = { method, headers: {} };
    if (method === "PUT") {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(value);
    }
    try {
      const response = await fetch(url, options);
      if ((response.status === 401 || response.status === 403) && this.refreshToken) {
        await this.refreshTokenNow();
        url.searchParams.set("auth", this.idToken);
        const retry = await fetch(url, options);
        return this.readResponse(retry);
      }
      return this.readResponse(response);
    } catch (error) {
      if (error instanceof TypeError) throw new Error("Rete o Firebase non raggiungibili.");
      throw error;
    }
  }

  async refreshTokenNow() {
    this.expiresAt = 0;
    await this.ensureToken();
  }

  async fetchJson(url, options) {
    let response;
    try {
      response = await fetch(url, options);
    } catch (error) {
      if (error instanceof TypeError) throw new Error("Rete non disponibile o endpoint Firebase non raggiungibile.");
      throw error;
    }
    return this.readResponse(response);
  }

  async readResponse(response) {
    const raw = await response.text();
    let data = null;
    if (raw) {
      try { data = JSON.parse(raw); }
      catch { throw new Error("Firebase ha restituito una risposta non valida."); }
    }
    if (!response.ok) {
      const code = (typeof data?.error === "string" ? data.error : data?.error?.message) || `HTTP ${response.status}`;
      throw new Error(firebaseMessage(code));
    }
    return data;
  }
}

function firebaseMessage(code) {
  const known = {
    EMAIL_NOT_FOUND: "Email Firebase non trovata.",
    INVALID_PASSWORD: "Password Firebase non corretta.",
    INVALID_LOGIN_CREDENTIALS: "Email o password non corretti.",
    USER_DISABLED: "Questo account Firebase è disabilitato.",
    OPERATION_NOT_ALLOWED: "Abilita Email/Password in Firebase Authentication.",
    API_KEY_INVALID: "Web API key non valida.",
    PERMISSION_DENIED: "Lettura o scrittura negata dalle regole del Realtime Database.",
    NETWORK_REQUEST_FAILED: "Rete non disponibile.",
  };
  if (known[code]) return known[code];
  if (code.includes("Permission denied")) return "Accesso negato dalle regole del Realtime Database.";
  if (code.includes("INVALID_ARGUMENT") || code.includes("Invalid URL")) return "URL del Realtime Database non valido.";
  return code;
}

function readSavedPublicConfig() {
  try {
    const saved = JSON.parse(localStorage.getItem(CONFIG_KEY) || "{}");
    $("#apiKey").value = saved.apiKey || "";
    $("#databaseUrl").value = saved.databaseUrl || "";
    $("#expectedUid").value = saved.expectedUid || "";
  } catch { /* Ignore malformed local browser preferences. */ }
}

function validateDatabaseUrl(value) {
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || !url.hostname.endsWith("firebasedatabase.app") && !url.hostname.endsWith("firebaseio.com")) return false;
    return true;
  } catch { return false; }
}

function showLoginError(message) {
  const box = $("#loginError");
  box.textContent = message;
  box.hidden = false;
}

function setDatabaseState(online, label = "Firebase connesso") {
  state.databaseOnline = online;
  const pill = $("#connectionPill");
  pill.classList.toggle("connected", online);
  pill.classList.toggle("disconnected", !online);
  $("#connectionText").textContent = label;
  updateCommandAvailability();
}

function setThermostatState(online, reason = "") {
  state.statusOnline = online;
  const panel = $("#systemState");
  panel.classList.toggle("online", online);
  panel.classList.toggle("offline", !online);
  $("#systemStateText").textContent = online ? "ONLINE" : "OFFLINE";
  $("#lastUpdate").textContent = online && state.status?.updated_at
    ? `Aggiornato ${formatTime(state.status.updated_at)}`
    : reason || "Stato non aggiornato";
  updateCommandAvailability();
}

function updateCommandAvailability() {
  const active = Boolean(state.statusOnline && state.status?.boot_id && state.db);
  const manual = Boolean($("#manualToggle")?.checked);
  $$(".relay-action").forEach((button) => { button.disabled = !active || !manual; });
  $("#manualToggle").disabled = !active;
  $("#shutdownButton").disabled = !active;
}

function formatTime(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("it-IT", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(date);
}

function setText(id, value) { $(id).textContent = value; }

function normalizeChannelConfig(channelId) {
  const current = state.config?.channels?.[channelId] || DEFAULT_CONFIG.channels[channelId];
  return { ...DEFAULT_CONFIG.channels[channelId], ...current, schedule: Array.isArray(current.schedule) ? current.schedule : [] };
}

function renderConfig() {
  if (!state.config) return;
  for (const channelId of ["ch1", "ch2"]) {
    const channel = normalizeChannelConfig(channelId);
    const prefix = `#${channelId}`;
    const setpoint = $(`${prefix}Setpoint`);
    const hysteresis = $(`${prefix}Hysteresis`);
    const mode = $(`${prefix}Mode`);
    if (document.activeElement !== setpoint) setpoint.value = channel.setpoint ?? 20;
    if (document.activeElement !== hysteresis) hysteresis.value = channel.hysteresis ?? 0.5;
    if (document.activeElement !== mode) mode.value = channel.mode === "cooling" ? "cooling" : "heating";
    setText(`${prefix}PlanCount`, String(channel.schedule.length));
    setText(`${prefix}PlanState`, channel.schedule.length ? "Planning attivo" : "Nessun planning");
  }
}

function renderStatus(data) {
  state.status = data;
  const channels = data.channels || {};
  for (const name of ["CH1", "CH2"]) {
    const key = name.toLowerCase();
    const channel = channels[name] || {};
    setText(`#${key}Temperature`, channel.temperature == null ? "—" : Number(channel.temperature).toFixed(1));
    setText(`#${key}SetpointReadout`, `${channel.setpoint ?? "—"} °C`);
    setText(`#${key}HysteresisReadout`, `${channel.hysteresis ?? "—"} °C`);
    const modeText = channel.mode === 2 || channel.mode === "cooling" ? "COOLING" : "HEATING";
    setText(`#${key}ModeReadout`, modeText);
    const relayBadge = $(`#${key}RelayBadge`);
    const relayOn = Boolean(channel.relay);
    relayBadge.classList.toggle("active", relayOn);
    setText(`#${key}RelayText`, relayOn ? "RELAY ON" : "RELAY OFF");
    if (state.previousRelay[name] !== null && state.previousRelay[name] !== relayOn) {
      showToast(`${name}: relè ${relayOn ? "ON" : "OFF"}.`);
    }
    state.previousRelay[name] = relayOn;
  }
  const manual = Boolean(data.manual);
  $("#manualToggle").checked = manual;
  $("#manualIndicator").textContent = manual ? "MANUALE ATTIVO" : "AUTOMATICO";
  $("#manualIndicator").classList.toggle("enabled", manual);
  setText("#syncMessage", data.simulated ? "Backend simulato · nessun hardware collegato" : `Ultimo heartbeat ${formatTime(data.updated_at)}`);
  setThermostatState(true);
}

function renderDisconnected(reason) {
  setThermostatState(false, reason);
  for (const name of ["ch1", "ch2"]) {
    setText(`#${name}Temperature`, "—");
    const badge = $(`#${name}RelayBadge`);
    badge.classList.remove("active");
    setText(`#${name}RelayText`, "—");
  }
  setText("#syncMessage", reason || "In attesa di heartbeat dal Raspberry Pi.");
}

function showToast(message, kind = "", duration = 4200) {
  const toast = document.createElement("div");
  toast.className = `toast ${kind}`.trim();
  toast.textContent = message;
  $("#toastRegion").append(toast);
  window.setTimeout(() => toast.remove(), duration);
}

function showDashboard() {
  $("#loginView").hidden = true;
  $("#dashboardView").hidden = false;
  $("#currentDate").textContent = new Intl.DateTimeFormat("it-IT", { weekday: "long", day: "numeric", month: "long" }).format(new Date()).toUpperCase();
  setDatabaseState(true);
  renderConfig();
  pollLoop();
}

async function handleLogin(event) {
  event.preventDefault();
  const button = $("#loginButton");
  const error = $("#loginError");
  error.hidden = true;
  const apiKey = $("#apiKey").value.trim();
  const databaseUrl = $("#databaseUrl").value.trim();
  const email = $("#email").value.trim();
  const passwordInput = $("#password");
  const password = passwordInput.value;
  const expectedUid = $("#expectedUid").value.trim();
  if (!validateDatabaseUrl(databaseUrl)) {
    showLoginError("Inserisci l’URL HTTPS del tuo Realtime Database, ad esempio https://nome-default-rtdb.europe-west1.firebasedatabase.app.");
    return;
  }
  if (!apiKey || !email || !password) {
    showLoginError("Completa API key, email e password.");
    return;
  }
  button.disabled = true;
  $("#loginButton span:first-child").textContent = "Connessione…";
  try {
    state.db = new FirebaseRestClient({ apiKey, databaseUrl, expectedUid, email, password });
    await state.db.signIn();
    state.config = await state.db.get("thermostat/config") || structuredClone(DEFAULT_CONFIG);
    localStorage.setItem(CONFIG_KEY, JSON.stringify({ apiKey, databaseUrl, expectedUid }));
    passwordInput.value = "";
    showDashboard();
  } catch (error) {
    state.db = null;
    passwordInput.value = "";
    showLoginError(error.message || "Accesso Firebase non riuscito.");
  } finally {
    button.disabled = false;
    $("#loginButton span:first-child").textContent = "Connetti";
  }
}

async function pollLoop() {
  if (!state.db) return;
  try {
    const status = await state.db.get("thermostat/status");
    setDatabaseState(true);
    if (!status || typeof status !== "object") {
      state.status = null;
      renderDisconnected("In attesa di heartbeat dal Raspberry Pi.");
    } else {
      const updated = Date.parse(status.updated_at || "");
      const age = (Date.now() - updated) / 1000;
      if (!Number.isFinite(updated) || age < -60 || age > STATUS_TIMEOUT_SECONDS) {
        state.status = status;
        renderDisconnected(Number.isFinite(age) ? `Heartbeat vecchio · ${Math.max(0, Math.floor(age))}s` : "Timestamp di stato non valido.");
      } else {
        renderStatus(status);
        checkPendingRevision(status);
      }
    }
    if (Date.now() - (state.lastConfigRead || 0) >= CONFIG_POLL_MS) {
      const config = await state.db.get("thermostat/config");
      if (config && typeof config === "object") {
        state.config = config;
        renderConfig();
      }
      state.lastConfigRead = Date.now();
    }
  } catch (error) {
    setDatabaseState(false, "Firebase non raggiungibile");
    renderDisconnected(error.message || "Errore di comunicazione con Firebase.");
  } finally {
    if (state.db) state.pollTimer = window.setTimeout(pollLoop, STATUS_POLL_MS);
  }
}

function checkPendingRevision(status) {
  if (!state.pendingRevision || Number(status.config_revision ?? -1) < state.pendingRevision) return;
  const revision = state.pendingRevision;
  state.pendingRevision = null;
  window.clearTimeout(state.pendingTimer);
  setText("#syncMessage", `Configurazione ${revision} salvata sul Raspberry · ${formatTime(status.updated_at)}`);
  showToast("Configurazione ricevuta e salvata localmente dal Raspberry.");
}

async function writeConfig(nextConfig, message = "Modifica inviata a Firebase.") {
  if (!state.db) throw new Error("Accedi a Firebase prima di salvare.");
  state.updatingConfig = true;
  nextConfig.revision = Math.max(Number(nextConfig.revision || 0) + 1, Date.now());
  nextConfig.updated_at = new Date().toISOString();
  state.config = nextConfig;
  renderConfig();
  await state.db.put("thermostat/config", nextConfig);
  state.pendingRevision = nextConfig.revision;
  setText("#syncMessage", `Revisione ${nextConfig.revision} inviata · in attesa del Raspberry…`);
  showToast(message, "pending");
  window.clearTimeout(state.pendingTimer);
  state.pendingTimer = window.setTimeout(() => {
    if (state.pendingRevision === nextConfig.revision) {
      showToast("Firebase ha ricevuto la modifica, ma il Raspberry non ha ancora confermato il salvataggio locale.", "pending", 7000);
    }
  }, 6500);
  state.updatingConfig = false;
}

function cloneCurrentConfig() {
  const source = state.config || DEFAULT_CONFIG;
  return structuredClone(source);
}

async function saveChannelField(channelId, field) {
  try {
    const input = $(`#${channelId}${field[0].toUpperCase()}${field.slice(1)}`);
    let value;
    if (field === "mode") value = input.value;
    else {
      if (!input.value.trim()) throw new Error("Inserisci un valore numerico.");
      value = Number(input.value.replace?.(",", ".") ?? input.value);
      if (!Number.isFinite(value) || (field === "hysteresis" && value < 0)) throw new Error("Inserisci un valore numerico valido.");
    }
    const next = cloneCurrentConfig();
    next.channels ||= {};
    next.channels[channelId] = { ...DEFAULT_CONFIG.channels[channelId], ...(next.channels[channelId] || {}) };
    next.channels[channelId][field] = value;
    if (field === "setpoint") next.channels[channelId].schedule = [];
    await writeConfig(next, `${channelId.toUpperCase()}: ${field === "mode" ? value : `${value} °C`} inviato.`);
  } catch (error) {
    showToast(error.message || "Salvataggio non riuscito.", "error");
  }
}

function createPlanRow(start = "", setpoint = "") {
  const row = document.createElement("div");
  row.className = "plan-row";
  const startLabel = document.createElement("label");
  startLabel.append(document.createTextNode("Inizio intervallo"));
  const startInput = document.createElement("input");
  startInput.type = "datetime-local";
  startInput.value = start;
  startInput.required = true;
  startLabel.append(startInput);
  const setpointLabel = document.createElement("label");
  setpointLabel.append(document.createTextNode("Setpoint °C"));
  const setpointInput = document.createElement("input");
  setpointInput.type = "number";
  setpointInput.inputMode = "decimal";
  setpointInput.step = "0.1";
  setpointInput.value = setpoint;
  setpointInput.required = true;
  setpointLabel.append(setpointInput);
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "remove-row";
  remove.setAttribute("aria-label", "Rimuovi intervallo");
  remove.textContent = "×";
  remove.addEventListener("click", () => row.remove());
  row.append(startLabel, setpointLabel, remove);
  $("#planRows").append(row);
}

function localInputFromIso(value) {
  if (!value) return "";
  const raw = String(value).slice(0, 16);
  return raw;
}

function openPlan(channelId) {
  state.activeChannel = channelId;
  const schedule = normalizeChannelConfig(channelId).schedule;
  setText("#planTitle", `Planning · ${channelId.toUpperCase()}`);
  $("#planRows").replaceChildren();
  $("#planError").hidden = true;
  if (schedule.length) {
    schedule.forEach((entry) => createPlanRow(localInputFromIso(entry[0]), entry[2]));
  } else {
    createPlanRow();
  }
  $("#planDialog").showModal();
}

async function savePlan() {
  const errorBox = $("#planError");
  errorBox.hidden = true;
  const rows = $$(".plan-row", $("#planRows"));
  const parsed = [];
  for (const row of rows) {
    const inputs = $$('input', row);
    const start = inputs[0].value;
    const setpoint = Number(inputs[1].value);
    if (!start || !Number.isFinite(setpoint)) {
      errorBox.textContent = "Completa data, ora e setpoint per ogni intervallo.";
      errorBox.hidden = false;
      return;
    }
    parsed.push({ start, setpoint, time: new Date(start).getTime() });
  }
  parsed.sort((a, b) => a.time - b.time);
  for (let index = 1; index < parsed.length; index += 1) {
    if (parsed[index - 1].time === parsed[index].time) {
      errorBox.textContent = "Due intervalli non possono iniziare nello stesso momento.";
      errorBox.hidden = false;
      return;
    }
  }
  const schedule = parsed.map((item, index) => [
    `${item.start}:00`,
    index + 1 < parsed.length ? `${parsed[index + 1].start}:00` : "2099-12-31T23:59:00",
    item.setpoint,
  ]);
  try {
    const next = cloneCurrentConfig();
    next.channels ||= {};
    next.channels[state.activeChannel] = { ...DEFAULT_CONFIG.channels[state.activeChannel], ...(next.channels[state.activeChannel] || {}), schedule };
    await writeConfig(next, "Planning inviato a Firebase.");
    $("#planDialog").close();
  } catch (exception) {
    errorBox.textContent = exception.message || "Non è stato possibile salvare il planning.";
    errorBox.hidden = false;
  }
}

async function sendCommand(path, value) {
  if (!state.db || !state.statusOnline || !state.status?.boot_id) throw new Error("Il termostato non risulta online.");
  const commandId = globalThis.crypto?.randomUUID
    ? globalThis.crypto.randomUUID().replaceAll("-", "")
    : `${Date.now().toString(16)}${Math.random().toString(16).slice(2)}`;
  const command = { id: commandId, boot_id: state.status.boot_id, value };
  await state.db.put(`thermostat/commands/${path}`, command);
}

async function handleManualToggle() {
  const checkbox = $("#manualToggle");
  const desired = checkbox.checked;
  try {
    await sendCommand("manual_enabled", desired);
    showToast(`Richiesta modalità manuale ${desired ? "ON" : "OFF"} inviata.`, "pending");
  } catch (error) {
    checkbox.checked = !desired;
    showToast(error.message, "error");
  }
  updateCommandAvailability();
}

async function handleRelay(button) {
  try {
    const channel = button.dataset.channel;
    const value = button.dataset.value === "true";
    await sendCommand(`manual_relay/${channel}`, value);
    showToast(`${channel.toUpperCase()}: comando ${value ? "ON" : "OFF"} inviato.`, "pending");
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function handleShutdown() {
  if (!state.statusOnline) return;
  if (!window.confirm("Vuoi inviare al Raspberry il comando di spegnimento?")) return;
  try {
    await sendCommand("shutdown", true);
    showToast("Comando di spegnimento inviato al Raspberry.", "pending");
  } catch (error) {
    showToast(error.message, "error");
  }
}

function signOut() {
  window.clearTimeout(state.pollTimer);
  window.clearTimeout(state.pendingTimer);
  state.db = null;
  state.config = null;
  state.status = null;
  state.pendingRevision = null;
  state.statusOnline = false;
  state.databaseOnline = false;
  $("#dashboardView").hidden = true;
  $("#loginView").hidden = false;
  $("#password").value = "";
}

function bindEvents() {
  $("#loginForm").addEventListener("submit", handleLogin);
  $("#signOutButton").addEventListener("click", signOut);
  $$(".save-config").forEach((button) => button.addEventListener("click", () => saveChannelField(button.dataset.channel, button.dataset.field)));
  $$(".open-plan").forEach((button) => button.addEventListener("click", () => openPlan(button.dataset.channel)));
  $$(".relay-action").forEach((button) => button.addEventListener("click", () => handleRelay(button)));
  $("#manualToggle").addEventListener("change", handleManualToggle);
  $("#shutdownButton").addEventListener("click", handleShutdown);
  $("#addPlanRow").addEventListener("click", () => createPlanRow());
  $("#savePlan").addEventListener("click", savePlan);
  $("#clearPlan").addEventListener("click", async () => {
    if (!state.activeChannel) return;
    try {
      const next = cloneCurrentConfig();
      next.channels[state.activeChannel] = { ...DEFAULT_CONFIG.channels[state.activeChannel], ...(next.channels[state.activeChannel] || {}), schedule: [] };
      await writeConfig(next, "Planning rimosso.");
      $("#planDialog").close();
    } catch (error) {
      $("#planError").textContent = error.message;
      $("#planError").hidden = false;
    }
  });
  $$(".close-dialog").forEach((button) => button.addEventListener("click", (event) => {
    if (button.tagName === "BUTTON" && !button.closest("form")) {
      event.preventDefault();
      $("#planDialog").close();
    }
  }));
  $("#planDialog").addEventListener("click", (event) => {
    if (event.target === $("#planDialog")) $("#planDialog").close();
  });
}

readSavedPublicConfig();
bindEvents();
