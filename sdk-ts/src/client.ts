import EventSource from "eventsource";
import fetch, { type HeadersInit, type Response as FetchResponse } from "node-fetch";

export interface SignalOptions {
  apiKey: string;
  baseUrl?: string;
}

export interface EscalateParams {
  context: string;
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

export class Signal {
  private readonly apiKey: string;
  private readonly baseUrl: string;

  constructor(options: SignalOptions) {
    this.apiKey = options.apiKey;
    this.baseUrl = (options.baseUrl ?? "http://localhost:8000").replace(/\/+$/, "");
  }

  async escalate(params: EscalateParams): Promise<EscalationResult> {
    const timeoutSeconds = params.timeoutSeconds ?? 3600;
    const pollIntervalSeconds = params.pollIntervalSeconds ?? 3;
    const deadline = Date.now() + timeoutSeconds * 1000;

    const response = await fetch(`${this.baseUrl}/v1/escalations`, {
      method: "POST",
      headers: this.jsonHeaders(),
      body: JSON.stringify({
        context: params.context,
        question: params.question,
        agent_id: params.agentId,
        action: params.action ?? null,
        metadata: params.metadata ?? {},
      }),
    });
    await this.assertOk(response);
    const created = (await response.json()) as { escalation_id: string };

    try {
      return await this.waitForStream(created.escalation_id, deadline);
    } catch {
      return await this.pollUntilResponse(created.escalation_id, deadline, pollIntervalSeconds);
    }
  }

  async check(params: CheckParams): Promise<CheckResult> {
    const response = await fetch(`${this.baseUrl}/v1/check`, {
      method: "POST",
      headers: this.jsonHeaders(),
      body: JSON.stringify({
        action: params.action,
        agent_id: params.agentId,
        context: params.context,
      }),
    });
    await this.assertOk(response);
    const data = (await response.json()) as {
      result: string;
      rule_id: string | null;
      reasoning: string;
      modification: Record<string, unknown> | null;
    };
    return {
      result: data.result,
      ruleId: data.rule_id,
      reasoning: data.reasoning,
      modification: data.modification,
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
