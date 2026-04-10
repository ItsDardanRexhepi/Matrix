/**
 * WebSocket client for real-time bidirectional chat.
 */

import type { Agent, WebSocketMessage, WebSocketResponse } from './types';

type MessageHandler = (response: WebSocketResponse) => void;

export class OpenMatrixWebSocket {
  private url: string;
  private ws: WebSocket | null = null;
  private handlers: Map<string, MessageHandler[]> = new Map();
  private defaultAgent: Agent;
  private sessionId: string;

  constructor(
    baseUrl: string = 'ws://localhost:18790',
    options: { defaultAgent?: Agent; sessionId?: string } = {}
  ) {
    this.url = baseUrl.replace(/^http/, 'ws').replace(/\/+$/, '') + '/ws';
    this.defaultAgent = options.defaultAgent || 'trinity';
    this.sessionId = options.sessionId || `ws-${Date.now()}`;
  }

  /**
   * Connect to the WebSocket endpoint.
   */
  async connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(this.url);
      this.ws.onopen = () => resolve();
      this.ws.onerror = (e) => reject(new Error('WebSocket connection failed'));
      this.ws.onmessage = (event) => {
        try {
          const data: WebSocketResponse = JSON.parse(event.data);
          const handlers = this.handlers.get(data.type) || [];
          handlers.forEach((h) => h(data));
          const allHandlers = this.handlers.get('*') || [];
          allHandlers.forEach((h) => h(data));
        } catch {
          // Ignore parse errors
        }
      };
    });
  }

  /**
   * Send a chat message over the WebSocket.
   */
  send(message: string, options: { agent?: Agent; sessionId?: string } = {}): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error('WebSocket not connected');
    }
    const payload: WebSocketMessage = {
      type: 'chat',
      message,
      agent: options.agent || this.defaultAgent,
      session_id: options.sessionId || this.sessionId,
    };
    this.ws.send(JSON.stringify(payload));
  }

  /**
   * Register an event handler.
   *
   * @param event - Event type ('token', 'done', 'error', or '*' for all)
   * @param handler - Callback function
   */
  on(event: string, handler: MessageHandler): void {
    const existing = this.handlers.get(event) || [];
    existing.push(handler);
    this.handlers.set(event, existing);
  }

  /**
   * Remove an event handler.
   */
  off(event: string, handler: MessageHandler): void {
    const existing = this.handlers.get(event) || [];
    this.handlers.set(
      event,
      existing.filter((h) => h !== handler)
    );
  }

  /**
   * Close the WebSocket connection.
   */
  close(): void {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  /**
   * Check if the WebSocket is connected.
   */
  get connected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }
}
