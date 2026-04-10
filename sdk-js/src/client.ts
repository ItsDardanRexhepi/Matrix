/**
 * Main HTTP client for the 0pnMatrx gateway.
 *
 * Provides methods for chat, health checks, memory operations,
 * blockchain actions, subscription management, and component registry.
 */

import type {
  Agent,
  ChatRequest,
  ChatResponse,
  HealthResponse,
  StatusResponse,
  SubscriptionStatus,
  ComponentManifest,
  ComponentEntry,
} from './types';
import { OpenMatrixStream } from './stream';

export class OpenMatrixClient {
  private baseUrl: string;
  private apiKey?: string;
  private walletSession?: string;
  private defaultAgent: Agent;
  private sessionId: string;

  /**
   * Create a new 0pnMatrx client.
   *
   * @param baseUrl - Gateway URL (default: http://localhost:18790)
   * @param options - Configuration options
   */
  constructor(
    baseUrl: string = 'http://localhost:18790',
    options: {
      apiKey?: string;
      walletSession?: string;
      defaultAgent?: Agent;
      sessionId?: string;
    } = {}
  ) {
    this.baseUrl = baseUrl.replace(/\/+$/, '');
    this.apiKey = options.apiKey;
    this.walletSession = options.walletSession;
    this.defaultAgent = options.defaultAgent || 'trinity';
    this.sessionId = options.sessionId || `sdk-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  }

  /**
   * Build request headers.
   */
  private headers(): Record<string, string> {
    const h: Record<string, string> = {
      'Content-Type': 'application/json',
    };
    if (this.apiKey) {
      h['Authorization'] = `Bearer ${this.apiKey}`;
    }
    if (this.walletSession) {
      h['X-Wallet-Session'] = this.walletSession;
    }
    return h;
  }

  /**
   * Send a message to an agent and get a response.
   *
   * @param message - The message to send
   * @param options - Optional agent and session overrides
   * @returns The agent's response
   *
   * @example
   * ```typescript
   * const response = await client.chat('Convert my rental agreement to a smart contract');
   * console.log(response.response);
   * console.log(response.tool_calls);
   * ```
   */
  async chat(
    message: string,
    options: { agent?: Agent; sessionId?: string } = {}
  ): Promise<ChatResponse> {
    const body: ChatRequest = {
      message,
      agent: options.agent || this.defaultAgent,
      session_id: options.sessionId || this.sessionId,
    };

    const resp = await fetch(`${this.baseUrl}/chat`, {
      method: 'POST',
      headers: this.headers(),
      body: JSON.stringify(body),
    });

    if (!resp.ok) {
      const error = await resp.json().catch(() => ({ error: resp.statusText }));
      throw new Error(`Chat failed (${resp.status}): ${error.error || resp.statusText}`);
    }

    return resp.json();
  }

  /**
   * Stream a chat response via Server-Sent Events.
   *
   * @param message - The message to send
   * @param options - Optional agent and session overrides
   * @returns An async iterable of stream events
   *
   * @example
   * ```typescript
   * const stream = await client.chatStream('Tell me about DeFi');
   * for await (const event of stream) {
   *   if (event.event === 'token') {
   *     process.stdout.write(event.data.text as string);
   *   }
   * }
   * ```
   */
  async chatStream(
    message: string,
    options: { agent?: Agent; sessionId?: string } = {}
  ): Promise<OpenMatrixStream> {
    const body: ChatRequest = {
      message,
      agent: options.agent || this.defaultAgent,
      session_id: options.sessionId || this.sessionId,
    };

    const resp = await fetch(`${this.baseUrl}/chat/stream`, {
      method: 'POST',
      headers: this.headers(),
      body: JSON.stringify(body),
    });

    if (!resp.ok) {
      throw new Error(`Stream failed (${resp.status})`);
    }

    return new OpenMatrixStream(resp);
  }

  /**
   * Check gateway health.
   */
  async health(): Promise<HealthResponse> {
    const resp = await fetch(`${this.baseUrl}/health`);
    return resp.json();
  }

  /**
   * Get full platform status.
   */
  async status(): Promise<StatusResponse> {
    const resp = await fetch(`${this.baseUrl}/status`, {
      headers: this.headers(),
    });
    return resp.json();
  }

  /**
   * Read agent memory.
   */
  async readMemory(agent: Agent = 'neo'): Promise<Record<string, unknown>> {
    const resp = await fetch(`${this.baseUrl}/memory/read`, {
      method: 'POST',
      headers: this.headers(),
      body: JSON.stringify({ agent }),
    });
    return resp.json();
  }

  /**
   * Write to agent memory.
   */
  async writeMemory(
    agent: Agent,
    key: string,
    value: unknown
  ): Promise<{ success: boolean }> {
    const resp = await fetch(`${this.baseUrl}/memory/write`, {
      method: 'POST',
      headers: this.headers(),
      body: JSON.stringify({ agent, key, value }),
    });
    return resp.json();
  }

  /**
   * Get the component registry.
   */
  async getComponents(): Promise<ComponentManifest> {
    const resp = await fetch(`${this.baseUrl}/extensions/registry`);
    return resp.json();
  }

  /**
   * Get a specific component by ID.
   */
  async getComponent(componentId: string): Promise<ComponentEntry> {
    const resp = await fetch(
      `${this.baseUrl}/extensions/registry/${componentId}`
    );
    return resp.json();
  }

  /**
   * Get current subscription status.
   */
  async subscriptionStatus(): Promise<SubscriptionStatus> {
    const resp = await fetch(`${this.baseUrl}/subscription/status`, {
      headers: this.headers(),
    });
    return resp.json();
  }

  /**
   * Start a checkout session for a subscription tier.
   */
  async checkout(
    tier: 'pro' | 'enterprise',
    options: { successUrl?: string; cancelUrl?: string } = {}
  ): Promise<{ checkout_url: string }> {
    const resp = await fetch(`${this.baseUrl}/subscription/checkout`, {
      method: 'POST',
      headers: this.headers(),
      body: JSON.stringify({
        tier,
        success_url: options.successUrl || `${this.baseUrl}/pricing?status=success`,
        cancel_url: options.cancelUrl || `${this.baseUrl}/pricing?status=cancelled`,
      }),
    });
    return resp.json();
  }

  /**
   * Set the wallet session token (from SIWE auth).
   */
  setWalletSession(token: string): void {
    this.walletSession = token;
  }

  /**
   * Set the API key.
   */
  setApiKey(key: string): void {
    this.apiKey = key;
  }
}
