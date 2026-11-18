/** OpenCode 1.19.5 server-plugin bridge. */
import { realpathSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const MAX_BRIDGE_BYTES = 32 * 1024;
const MAX_QUEUE = 64;
const HELPER_TIMEOUT_MS = 5000;
const NATIVE_LOOKUP_TIMEOUT_MS = 2000;
const HERDR_MARKERS = [
  "HERDR_BIN_PATH",
  "HERDR_ENV",
  "HERDR_PANE_ID",
  "HERDR_SOCKET_PATH",
  "HERDR_TAB_ID",
  "HERDR_WORKSPACE_ID",
];
const PLUGIN_FILE = realpathSync(fileURLToPath(import.meta.url));
const HELPER = path.resolve(path.dirname(PLUGIN_FILE), "../../bin/harness-herdr-hooks");
const supportedEvents = new Set([
  "session.created",
  "session.updated",
  "session.status",
  "session.idle",
]);

function rootsHint() {
  const home = process.env.HOME;
  const configDir = process.env.OPENCODE_CONFIG_DIR ||
    (process.env.XDG_CONFIG_HOME ? `${process.env.XDG_CONFIG_HOME}/opencode` : home ? `${home}/.config/opencode` : null);
  const dataDir = process.env.XDG_DATA_HOME ? `${process.env.XDG_DATA_HOME}/opencode` : home ? `${home}/.local/share/opencode` : null;
  const stateDir = process.env.XDG_STATE_HOME ? `${process.env.XDG_STATE_HOME}/opencode` : home ? `${home}/.local/state/opencode` : null;
  return { config_dir: configDir, data_dir: dataDir, state_dir: stateDir };
}

function insideHerdr() {
  return process.env.HERDR_ENV === "1" &&
    ["HERDR_PANE_ID", "HERDR_TAB_ID", "HERDR_WORKSPACE_ID", "HERDR_SOCKET_PATH"]
      .every((name) => typeof process.env[name] === "string" && process.env[name].length > 0 && process.env[name].length <= 4096);
}

function safeServerUrl(input) {
  try {
    const url = new URL(input);
    if (!new Set(["http:", "https:"]).has(url.protocol)) return null;
    if (url.username || url.password || url.search || url.hash) return null;
    return url.toString().replace(/\/$/, "");
  } catch {
    return null;
  }
}

async function forward(envelope) {
  const wire = JSON.stringify(envelope);
  if (Buffer.byteLength(wire, "utf8") > MAX_BRIDGE_BYTES) return;
  let child;
  let timer;
  try {
    child = Bun.spawn([HELPER, "opencode-event"], {
      stdin: "pipe",
      stdout: "ignore",
      stderr: "ignore",
      env: {
        PATH: process.env.PATH || "",
        ...(process.env.HOME ? { HOME: process.env.HOME } : {}),
        ...(process.env.TERM ? { TERM: process.env.TERM } : {}),
        ...(process.env.LANG ? { LANG: process.env.LANG } : {}),
        ...(process.env.XDG_RUNTIME_DIR ? { XDG_RUNTIME_DIR: process.env.XDG_RUNTIME_DIR } : {}),
        ...Object.fromEntries(HERDR_MARKERS.flatMap((name) => {
          const value = process.env[name];
          if (typeof value !== "string" || value.length > 4096) return [];
          if (name === "HERDR_ENV" && value !== "1") return [];
          return [[name, value]];
        })),
      },
    });
    child.stdin.write(wire);
    child.stdin.end();
    await Promise.race([
      child.exited,
      new Promise((resolve) => {
        timer = setTimeout(() => { try { child.kill(); } catch {} resolve(); }, HELPER_TIMEOUT_MS);
      }),
    ]);
  } catch {
    try { child?.kill(); } catch {}
  } finally {
    if (timer) clearTimeout(timer);
  }
}

async function buildEnvelope(task, client, backendUrl, sessionInfo) {
  const { eventType, props } = task;
  const info = props.info;
  const sessionId = info && typeof info === "object" && typeof info.id === "string"
    ? info.id
    : typeof props.sessionID === "string" ? props.sessionID : null;
  if (!sessionId) return null;
  if (info && typeof info === "object" && typeof info.id === "string") {
    sessionInfo.set(sessionId, {
      id: info.id,
      parentID: typeof info.parentID === "string" ? info.parentID : null,
      title: typeof info.title === "string" ? info.title : null,
      directory: typeof info.directory === "string" ? info.directory : null,
      createdAt: Number.isFinite(info.time?.created) ? info.time.created : 0,
    });
    if (sessionInfo.size > 2048) sessionInfo.delete(sessionInfo.keys().next().value);
  }
  let knownInfo = sessionInfo.get(sessionId);
  if (!knownInfo && ["session.status", "session.idle"].includes(eventType) && client?.session?.get) {
    let timer;
    try {
      knownInfo = await Promise.race([
        client.session.get({ path: { id: sessionId } }).then((result) => {
          const value = result?.data ?? result;
          if (!value || typeof value.id !== "string" || value.id !== sessionId || typeof value.directory !== "string") return null;
          return {
            id: value.id,
            parentID: typeof value.parentID === "string" ? value.parentID : null,
            title: typeof value.title === "string" ? value.title : null,
            directory: value.directory,
            createdAt: Number.isFinite(value.time?.created) ? value.time.created : 0,
          };
        }),
        new Promise((resolve) => { timer = setTimeout(() => resolve(null), NATIVE_LOOKUP_TIMEOUT_MS); }),
      ]);
      if (knownInfo) {
        sessionInfo.set(sessionId, knownInfo);
        if (sessionInfo.size > 2048) sessionInfo.delete(sessionInfo.keys().next().value);
      }
    } catch { knownInfo = null; }
    finally { if (timer) clearTimeout(timer); }
  }
  if (!knownInfo || typeof knownInfo.directory !== "string" || !knownInfo.directory) return null;
  const session = {
    id: sessionId,
    parent_id: knownInfo.parentID,
    title: knownInfo.title,
    directory: knownInfo.directory,
    created_at: knownInfo.createdAt,
  };
  const statusHint = props.status?.type === "busy" ? { type: "busy" } : null;
  return {
    schema_version: 1,
    harness: "opencode",
    event_kind: eventType,
    backend: { server_url: backendUrl, pid: process.pid },
    roots: rootsHint(),
    session,
    ...(statusHint ? { status: statusHint } : {}),
  };
}

function enqueue(queue, task, client, backendUrl, sessionInfo) {
  if (queue.length >= MAX_QUEUE) return;
  queue.push(task);
  if (queue.draining) return;
  queue.draining = true;
  void (async () => {
    try {
      while (queue.length) {
        const envelope = await buildEnvelope(queue.shift(), client, backendUrl, sessionInfo);
        if (envelope) await forward(envelope);
      }
    } finally {
      queue.draining = false;
      if (queue.length) enqueue(queue, queue.shift());
    }
  })();
}

export const HarnessHerdrHooks = async ({ serverUrl, client }) => {
  const backendUrl = safeServerUrl(serverUrl?.toString?.());
  if (!backendUrl || !insideHerdr()) return {};
  if (["OPENCODE_CONFIG", "OPENCODE_CONFIG_CONTENT", "OPENCODE_DB"].some((name) => process.env[name] !== undefined)) {
    console.warn("harness-herdr-hooks: unqualified OpenCode configuration override; integration disabled");
    return {};
  }
  const sessionInfo = new Map();
  const queue = [];
  return {
    event: async ({ event }) => {
      if (!event || !supportedEvents.has(event.type)) return;
      const props = event.properties;
      if (!props) return;
      enqueue(queue, { eventType: event.type, props }, client, backendUrl, sessionInfo);
    },
  };
};

export const server = HarnessHerdrHooks;
