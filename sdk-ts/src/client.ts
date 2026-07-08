import EventSource from "eventsource";
import fetch, { type HeadersInit, type Response as FetchResponse } from "node-fetch";

export interface SignalOptions {
  apiKey: string;
  baseUrl?: string;
  devMode?: boolean;
  autoEnrich?: boolean;
}

export interface EscalateParams {
  context: string | Record<string, unknown>;
  question: string;
  agentId: string;
  action?: string;
  metadata?: Record<string, unknown>;
  timeoutSeconds?: number;
  pollIntervalSeconds?: number;
}

export interface EscalationResult {
  decision: string | null;
  ruleId: string | null;
  autoResolved: boolean;
}

export interface CheckParams {
  action: string;
  agentId: string;
  context: Record<string, unknown>;
}

export interface CheckResult {
  result: string;
  ruleId: string | null;
  reasoning: string;
  modification: Record<string, unknown> | null;
  contextWarnings: string[];
}

type EscalationState = {
  event?: string;
  escalation_id?: string;
  status: string;
  human_decision?: string | null;
  rule_id?: string | null;
  auto_resolved?: boolean;
  finalized?: boolean;
  finalization_reason?: string | null;
};

const personScalarFields = new Set([
  "actor",
  "approver",
  "author",
  "creator",
  "owner",
  "requester",
  "reviewer",
  "submitter",
  "user",
]);

const builtinContextAliasesRaw: Record<string, string> = {
  "allowed pairs": "route.pair.cap",
  allowed_pairs: "route.pair.cap",
  "departure date": "departure.date",
  departure_date: "departure.date",
  "destination airport": "destination.airports",
  "destination airports": "destination.airports",
  destinations: "destination.airports",
  "non stop": "nonstop.only",
  "non-stop": "nonstop.only",
  non_stop: "nonstop.only",
  nonstop: "nonstop.only",
  "nonstop only": "nonstop.only",
  nonstop_only: "nonstop.only",
  "operational risk": "operational.risk",
  "origin airport": "origin.airports",
  "origin airports": "origin.airports",
  origins: "origin.airports",
  "provider limitation": "provider.limitation",
  "provider limitations": "provider.limitation",
  "requested pairs": "requested.route.pairs",
  "requested route pairs": "requested.route.pairs",
  requested_pairs: "requested.route.pairs",
  "return date": "return.date",
  return_date: "return.date",
  "route pair cap": "route.pair.cap",
  "route-pair cap": "route.pair.cap",
  route_pair_cap: "route.pair.cap",
  "route pairs requested": "requested.route.pairs",
  "routes requested per pair": "routes.requested.per.pair",
  "routes requested per route pair": "routes.requested.per.pair",
  routes_requested_per_pair: "routes.requested.per.pair",
  "sensitive data": "sensitive.data.included",
  "sensitive data included": "sensitive.data.included",
  "trip type": "trip.type",
};

export function canonicalizeFieldName(field: string): string {
  return String(field ?? "")
    .trim()
    .replace(/(?<=[a-z0-9])(?=[A-Z])/g, ".")
    .replace(/[^a-zA-Z0-9]+/g, ".")
    .replace(/\.+/g, ".")
    .replace(/^\.+|\.+$/g, "")
    .toLowerCase();
}

function canonicalizeScalarField(field: string): string {
  const canonical = canonicalizeFieldName(field);
  if (personScalarFields.has(canonical)) return `${canonical}.name`;
  return canonical;
}

function generatedAliasesForField(canonicalName: string): Set<string> {
  const aliases = new Set<string>([
    canonicalName,
    canonicalName.replaceAll(".", "_"),
    canonicalName.replaceAll(".", "-"),
  ]);
  const parts = canonicalName.split(".");
  if (parts.length > 1) {
    const camelTail = parts
      .slice(1)
      .map((part) => `${part[0]?.toUpperCase() ?? ""}${part.slice(1)}`)
      .join("");
    aliases.add(`${parts[0]}${camelTail}`);
  }
  return aliases;
}

export function builtinContextAliases(): Record<string, string> {
  const aliases: Record<string, string> = {};
  for (const [rawAlias, rawCanonical] of Object.entries(builtinContextAliasesRaw)) {
    const canonical = canonicalizeScalarField(rawCanonical);
    aliases[canonicalizeScalarField(rawAlias)] = canonical;
    aliases[canonicalizeScalarField(rawAlias.replaceAll(" ", "_"))] = canonical;
    aliases[canonicalizeScalarField(rawAlias.replaceAll(" ", "-"))] = canonical;
    aliases[canonicalizeScalarField(canonical)] = canonical;
    for (const generated of generatedAliasesForField(canonical)) {
      aliases[canonicalizeScalarField(generated)] = canonical;
    }
  }
  return aliases;
}

export function normalizeContext(context: Record<string, unknown>): {
  normalizedContext: Record<string, unknown>;
  warnings: string[];
} {
  const normalizedContext: Record<string, unknown> = {};
  const warnings: string[] = [];
  const aliases = builtinContextAliases();

  const visit = (value: unknown, prefix = ""): void => {
    if (value && typeof value === "object" && !Array.isArray(value)) {
      for (const [rawKey, child] of Object.entries(value as Record<string, unknown>)) {
        const key = canonicalizeFieldName(rawKey);
        const path = prefix ? `${prefix}.${key}` : key;
        visit(child, path);
      }
      return;
    }

    const normalizedPrefix = canonicalizeScalarField(prefix);
    const field = aliases[normalizedPrefix] ?? normalizedPrefix;
    if (!field) return;
    if (Object.prototype.hasOwnProperty.call(normalizedContext, field) && normalizedContext[field] !== value) {
      warnings.push(`Multiple values mapped to canonical field '${field}'.`);
    }
    normalizedContext[field] = value;
    if (field !== prefix) {
      warnings.push(`Normalized context field '${prefix}' to '${field}'.`);
    }
  };

  visit(context ?? {});
  return { normalizedContext, warnings };
}

export class Signal {
  private readonly apiKey: string;
  private readonly baseUrl: string;
  private readonly devMode: boolean;
  private readonly autoEnrich: boolean;

  constructor(options: SignalOptions) {
    this.apiKey = options.apiKey;
    this.baseUrl = (options.baseUrl ?? "http://localhost:8000").replace(/\/+$/, "");
    this.devMode = options.devMode ?? false;
    this.autoEnrich = options.autoEnrich ?? true;
  }

  private enrichContext(context: Record<string, unknown>): Record<string, unknown> {
    if (!this.autoEnrich) return context;

    const enriched = { ...context };
    enriched._signal_timestamp ??= new Date().toISOString();
    enriched._signal_environment ??= process.env.NODE_ENV ?? process.env.ENVIRONMENT ?? "unknown";

    return enriched;
  }

  private log(message: string, ...args: unknown[]): void {
    if (this.devMode) {
      console.log(`[Signal] ${message}`, ...args);
    }
  }

  private warn(message: string, ...args: unknown[]): void {
    console.warn(`[Signal] ${message}`, ...args);
  }

  async escalate(params: EscalateParams): Promise<EscalationResult> {
    const timeoutSeconds = params.timeoutSeconds ?? 3600;
    const pollIntervalSeconds = params.pollIntervalSeconds ?? 3;
    const deadline = Date.now() + timeoutSeconds * 1000;
    let outboundContext = params.context;
    const outboundMetadata = { ...(params.metadata ?? {}) };
    if (params.context && typeof params.context === "object") {
      // Auto-enrich context
      const enrichedContext = this.enrichContext(params.context);
      const { normalizedContext, warnings } = normalizeContext(enrichedContext);
      outboundContext = JSON.stringify(normalizedContext);
      outboundMetadata._signal_raw_context ??= params.context;
      if (warnings.length > 0) {
        outboundMetadata._signal_context_warnings ??= warnings;
      }
    }

    this.log(`Creating escalation: agentId=${params.agentId}, action=${params.action ?? "none"}`);
    this.log(`Context: ${typeof outboundContext === "string" ? outboundContext.substring(0, 200) : outboundContext}...`);

    const response = await fetch(`${this.baseUrl}/v1/escalations`, {
      method: "POST",
      headers: this.jsonHeaders(),
      body: JSON.stringify({
        context: outboundContext,
        question: params.question,
        agent_id: params.agentId,
        action: params.action ?? null,
        metadata: outboundMetadata,
      }),
    });
    await this.assertOk(response);
    const created = (await response.json()) as { escalation_id: string; context_warnings?: string[] };

    // Display context warnings from API
    const apiWarnings = created.context_warnings ?? [];
    if (apiWarnings.length > 0) {
      for (const warning of apiWarnings) {
        this.warn(`Context validation: ${warning}`);
      }
      this.log(`Received ${apiWarnings.length} context warnings from API`);
    }

    try {
      return await this.waitForStream(created.escalation_id, deadline);
    } catch {
      return await this.pollUntilResponse(created.escalation_id, deadline, pollIntervalSeconds);
    }
  }

  async check(params: CheckParams): Promise<CheckResult> {
    // Auto-enrich context
    const enrichedContext = this.enrichContext(params.context);
    const { normalizedContext, warnings } = normalizeContext(enrichedContext);

    this.log(`Checking policy: action=${params.action}, agentId=${params.agentId}`);
    this.log(`Normalized context: ${JSON.stringify(normalizedContext).substring(0, 200)}...`);

    const response = await fetch(`${this.baseUrl}/v1/check`, {
      method: "POST",
      headers: this.jsonHeaders(),
      body: JSON.stringify({
        action: params.action,
        agent_id: params.agentId,
        context: normalizedContext,
      }),
    });
    await this.assertOk(response);
    const data = (await response.json()) as {
      result: string;
      rule_id: string | null;
      reasoning: string;
      modification: Record<string, unknown> | null;
      context_warnings?: string[];
    };

    const allWarnings = [...warnings, ...(data.context_warnings ?? [])];
    if (allWarnings.length > 0) {
      this.log(`Check returned ${allWarnings.length} context warnings`);
    }

    return {
      result: data.result,
      ruleId: data.rule_id,
      reasoning: data.reasoning,
      modification: data.modification,
      contextWarnings: allWarnings,
    };
  }

  private waitForStream(escalationId: string, deadline: number): Promise<EscalationResult> {
    return new Promise((resolve, reject) => {
      const remainingMs = deadline - Date.now();
      if (remainingMs <= 0) {
        reject(new Error(`Escalation ${escalationId} did not receive a response in time`));
        return;
      }

      const source = new EventSource(`${this.baseUrl}/v1/escalations/${escalationId}/stream`, {
        headers: this.authHeaders(),
      });
      const timeout = setTimeout(() => {
        cleanup();
        reject(new Error(`Escalation ${escalationId} did not receive a response in time`));
      }, remainingMs);

      const cleanup = () => {
        clearTimeout(timeout);
        source.close();
      };

      const handleEvent = (event: MessageEvent) => {
        if (!event.data) return;
        const state = JSON.parse(String(event.data)) as EscalationState;
        if (state.event === "created") return;
        const finalized = state.finalized ?? state.status === "responded";
        if (finalized) {
          cleanup();
          resolve({
            decision: state.human_decision ?? null,
            ruleId: state.rule_id ?? null,
            autoResolved: Boolean(state.auto_resolved),
          });
        }
        if (state.status === "timed_out") {
          cleanup();
          reject(new Error(`Escalation ${escalationId} timed out`));
        }
      };

      source.addEventListener("response", handleEvent);
      source.onmessage = handleEvent;
      source.onerror = () => {
        cleanup();
        reject(new Error("SSE connection failed"));
      };
    });
  }

  private async pollUntilResponse(
    escalationId: string,
    deadline: number,
    pollIntervalSeconds: number,
  ): Promise<EscalationResult> {
    while (Date.now() < deadline) {
      const response = await fetch(`${this.baseUrl}/v1/escalations/${escalationId}`, {
        headers: this.authHeaders(),
      });
      await this.assertOk(response);
      const state = (await response.json()) as EscalationState;

      const finalized = state.finalized ?? state.status === "responded";
      if (finalized) {
        return {
          decision: state.human_decision ?? null,
          ruleId: state.rule_id ?? null,
          autoResolved: Boolean(state.auto_resolved),
        };
      }
      if (state.status === "timed_out") {
        throw new Error(`Escalation ${escalationId} timed out`);
      }

      await new Promise((resolve) => setTimeout(resolve, pollIntervalSeconds * 1000));
    }

    throw new Error(`Escalation ${escalationId} did not receive a response in time`);
  }

  private authHeaders(): HeadersInit {
    return { Authorization: `Bearer ${this.apiKey}` };
  }

  private jsonHeaders(): HeadersInit {
    return {
      ...this.authHeaders(),
      "Content-Type": "application/json",
    };
  }

  private async assertOk(response: FetchResponse): Promise<void> {
    if (!response.ok) {
      const body = await response.text();
      throw new Error(`Signal API request failed (${response.status}): ${body}`);
    }
  }
}
