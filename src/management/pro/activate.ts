/**
 * Activating PaperSearch Pro (user, 2026-11-21): a tester types the code the maintainer gave
 * them (the settings window's 激活并安装, or `paper-search pro activate`); PaperSearch's activation
 * server checks it, and its answer is kept in `<data>/pro/activation.json`, beside Pro.
 *
 * The server is not there yet (user, 2026-11-21: leave it empty, fill it in later). With no
 * address, activating says so and keeps nothing, and an install asks for no activation (a
 * development build, as with Pro's own switch). Once there is an address,
 * `pro install` needs an activation first.
 *
 * The exchange, a draft to settle with the server: POST the
 * address with `{"schemaVersion": 1, "code", "device", "client"}`; `device` is a random id kept
 * on this computer (`<data>/pro/device.json`), for the server to count computers. The answer:
 * `{"ok": true, "until": "2027-03-01"}` (`until` optional: no end) or `{"ok": false, "message"}`.
 */
import { randomUUID } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import axios from "axios";
import { USER_AGENT } from "../../config/constants.js";
import { paperSearchDataHome } from "../../infrastructure/school/index.js";

/** Where activation codes are checked; decided with the server. Empty: no server yet. */
export const DEFAULT_ACTIVATION_URL = "";

export type ActivationState = "none" | "active" | "expired";

export interface ActivationStatus {
  /** Whether there is a server to activate with. */
  service: boolean;
  state: ActivationState;
  /** The code's last four characters, all that is shown of it. */
  tail: string;
  /** The day it ends ("2027-03-01"); "" for none. */
  until: string;
}

export type ActivationResult =
  | { ok: true; state: "active"; tail: string; until: string }
  | { ok: false; code: string; message: string };

interface ActivationRecord {
  code: string;
  until?: string;
  activatedAt: string;
}

export function activationUrl(env: Record<string, string | undefined> = process.env): string {
  return (env.PAPER_SEARCH_PRO_ACTIVATION_URL ?? DEFAULT_ACTIVATION_URL).trim();
}

/** A code as typed, without spaces and in capitals; its form is settled with the server. */
export function normalizeCode(code: string): string {
  return code.replace(/\s+/g, "").toUpperCase();
}

const CODE = /^[A-Z0-9][A-Z0-9-]{4,62}[A-Z0-9]$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;

/** Pro's folder in PaperSearch's data (install.ts's proInstallDir), which an install keeps these records in. */
function proDir(env: Record<string, string | undefined>): string {
  return join(paperSearchDataHome(env), "pro");
}

function recordFile(env: Record<string, string | undefined>): string {
  return join(proDir(env), "activation.json");
}

function readRecord(env: Record<string, string | undefined>): ActivationRecord | undefined {
  try {
    const record = JSON.parse(readFileSync(recordFile(env), "utf8")) as Partial<ActivationRecord>;
    if (typeof record.code !== "string" || !record.code) return undefined;
    return { code: record.code, activatedAt: String(record.activatedAt ?? ""),
      ...(typeof record.until === "string" && DAY.test(record.until) ? { until: record.until } : {}) };
  } catch {
    return undefined;
  }
}

function today(now: Date): string {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** Whether this computer is activated, and until when (`pro status`, the settings window). */
export function activationStatus(env: Record<string, string | undefined> = process.env, now = new Date()): ActivationStatus {
  const record = readRecord(env);
  const service = activationUrl(env) !== "";
  if (!record) return { service, state: "none", tail: "", until: "" };
  const until = record.until ?? "";
  return { service, state: until && until < today(now) ? "expired" : "active", tail: record.code.slice(-4), until };
}

/** This computer's random id for the server, made the first time it is asked for. */
function deviceId(env: Record<string, string | undefined>): string {
  const file = join(proDir(env), "device.json");
  try {
    const known = JSON.parse(readFileSync(file, "utf8")) as { id?: unknown };
    if (typeof known.id === "string" && known.id) return known.id;
  } catch {
    // None yet, or unreadable: a new one.
  }
  const id = randomUUID();
  mkdirSync(proDir(env), { recursive: true });
  writeFileSync(file, `${JSON.stringify({ id }, null, 2)}\n`);
  return id;
}

/** Hands the code to the activation server and keeps its answer. */
export async function activatePro(options: {
  code: string;
  env?: Record<string, string | undefined>;
  timeoutMs?: number;
}): Promise<ActivationResult> {
  const env = options.env ?? process.env;
  const code = normalizeCode(options.code ?? "");
  if (!code) return { ok: false, code: "pro_activation_code_missing", message: "请输入激活码" };
  if (!CODE.test(code)) return { ok: false, code: "pro_activation_code_invalid", message: "激活码格式不对" };
  const url = activationUrl(env);
  if (!url) return { ok: false, code: "pro_activation_unavailable", message: "激活服务还没开放" };
  if (!url.startsWith("https://") && env.PAPER_SEARCH_PRO_ACTIVATION_URL === undefined) {
    return { ok: false, code: "pro_activation_unavailable", message: "激活服务还没开放" };
  }
  let answer: { ok?: unknown; until?: unknown; message?: unknown };
  try {
    const response = await axios.post(url, { schemaVersion: 1, code, device: deviceId(env), client: USER_AGENT },
      { timeout: options.timeoutMs ?? 30_000, responseType: "json", headers: { "User-Agent": USER_AGENT },
        // The server's refusal is an answer, read like any other.
        validateStatus: (status) => status < 500 });
    answer = (response.data && typeof response.data === "object" ? response.data : {}) as typeof answer;
  } catch (error) {
    return { ok: false, code: "pro_activation_failed",
      message: axios.isAxiosError(error) && !error.response ? "网络连接中断" : "激活服务出错" };
  }
  if (answer.ok !== true) {
    const message = typeof answer.message === "string" && answer.message.trim() ? answer.message.trim() : "激活码无效";
    return { ok: false, code: "pro_activation_rejected", message };
  }
  const until = typeof answer.until === "string" && DAY.test(answer.until) ? answer.until : "";
  const record: ActivationRecord = { code, activatedAt: new Date().toISOString(), ...(until ? { until } : {}) };
  mkdirSync(proDir(env), { recursive: true });
  writeFileSync(recordFile(env), `${JSON.stringify(record, null, 2)}\n`);
  return { ok: true, state: "active", tail: code.slice(-4), until };
}

/** Whether an install may go ahead: always without a server; with one, once activated. */
export function installAllowed(env: Record<string, string | undefined> = process.env): boolean {
  if (!activationUrl(env)) return true;
  return activationStatus(env).state === "active";
}
