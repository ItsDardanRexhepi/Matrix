/**
 * Main HTTP client for the 0pnMatrx gateway.
 *
 * Provides methods for chat, health checks, memory operations,
 * blockchain actions, in-app purchase verification, and component registry.
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

    return this.unwrap(resp, 'chat');
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
   * RUN-4 — turn a failed response into a thrown error.
   *
   * These methods used to end in a bare `return resp.json()`, checking
   * neither the HTTP status nor the payload's own status. The gateway wrapped
   * failures as HTTP 200 `{"status":"ok","data":{"status":"error"}}`, so a
   * caller received an error object typed as the success shape and carried on.
   * The server no longer inverts the envelope; this is the client half, and it
   * also protects a caller running against an older gateway.
   */
  private async unwrap<T>(resp: Response, what: string): Promise<T> {
    const body: unknown = await resp.json().catch(() => null);

    if (!resp.ok) {
      const detail =
        body && typeof body === 'object' && 'error' in body
          ? String((body as { error: unknown }).error)
          : resp.statusText;
      throw new Error(`${what} failed (${resp.status}): ${detail}`);
    }

    // Defence in depth: an older gateway may still report failure at HTTP 200.
    if (body && typeof body === 'object') {
      const outer = (body as { status?: unknown }).status;
      const inner = (body as { data?: { status?: unknown } }).data?.status;
      for (const s of [outer, inner]) {
        if (typeof s === 'string' && (s === 'error' || s === 'unavailable')) {
          throw new Error(`${what} failed: server reported status "${s}"`);
        }
      }
    }
    return body as T;
  }

  /**
   * Check gateway health.
   */
  async health(): Promise<HealthResponse> {
    const resp = await fetch(`${this.baseUrl}/health`);
    return this.unwrap(resp, 'health');
  }

  /**
   * Get full platform status.
   */
  async status(): Promise<StatusResponse> {
    const resp = await fetch(`${this.baseUrl}/status`, {
      headers: this.headers(),
    });
    return this.unwrap(resp, 'status');
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
    return this.unwrap(resp, 'readMemory');
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
    return this.unwrap(resp, 'writeMemory');
  }

  /**
   * Get the component registry.
   */
  async getComponents(): Promise<ComponentManifest> {
    const resp = await fetch(`${this.baseUrl}/extensions/registry`);
    return this.unwrap(resp, 'getComponents');
  }

  /**
   * Get a specific component by ID.
   */
  async getComponent(componentId: string): Promise<ComponentEntry> {
    const resp = await fetch(
      `${this.baseUrl}/extensions/registry/${componentId}`
    );
    return this.unwrap(resp, 'getComponent');
  }

  /**
   * @deprecated The gateway has no subscription-status or checkout endpoint.
   * Subscriptions are Apple In-App Purchases made in the MTRX app and reported
   * with {@link verifyIap}. This method used to call a status path the gateway
   * does not register, so it always failed with a 404; it now fails
   * without a request and says why.
   */
  async subscriptionStatus(): Promise<SubscriptionStatus> {
    throw new Error(
      'subscriptionStatus: this gateway has no subscription endpoint. ' +
        'Subscriptions are Apple In-App Purchases verified with verifyIap().'
    );
  }

  /**
   * @deprecated There is no checkout: subscriptions are sold through Apple
   * In-App Purchase in the MTRX app, not by a card checkout on the gateway.
   * This method used to post to a checkout path the gateway does not
   * register; it now fails without a request and says why.
   */
  async checkout(
    _tier: 'pro' | 'enterprise',
    _options: { successUrl?: string; cancelUrl?: string } = {}
  ): Promise<{ checkout_url: string }> {
    throw new Error(
      'checkout: this gateway has no checkout endpoint. Subscriptions are ' +
        'purchased in the MTRX app (Apple In-App Purchase) and reported with verifyIap().'
    );
  }

  /**
   * Report a StoreKit-signed transaction JWS to POST /api/v1/iap/verify.
   * The server verifies the full x5c chain to Apple's pinned root and records
   * the transaction (subscriptions and the consumable). Fail-closed
   * server-side: unconfigured -> 503, any verification failure -> 401.
   *
   * There is deliberately no method for /api/v1/iap/asn — that webhook is
   * called by Apple's servers (App Store Server Notifications), not by a client.
   */
  async verifyIap(
    signedTransaction: string
  ): Promise<{
    status: string;
    replay: boolean;
    transactionId: string;
    originalTransactionId: string;
    productId: string;
    productType: string;
    tier: string;
  }> {
    const resp = await fetch(`${this.baseUrl}/api/v1/iap/verify`, {
      method: 'POST',
      headers: this.headers(),
      body: JSON.stringify({ signedTransaction }),
    });
    return this.unwrap(resp, 'verifyIap');
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
