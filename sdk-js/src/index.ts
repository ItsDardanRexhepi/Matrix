/**
 * 0pnMatrx JavaScript/TypeScript SDK
 *
 * Provides a typed client for interacting with the 0pnMatrx gateway,
 * including chat, streaming, blockchain actions, and WebSocket connections.
 *
 * @example
 * ```typescript
 * import { OpenMatrixClient } from '@opnmatrx/sdk';
 *
 * const client = new OpenMatrixClient('http://localhost:18790');
 * const response = await client.chat('What can you do?');
 * console.log(response.response);
 * ```
 */

export { OpenMatrixClient } from './client';
export { OpenMatrixStream } from './stream';
export { OpenMatrixWebSocket } from './websocket';
export type {
  ChatRequest,
  ChatResponse,
  StreamEvent,
  HealthResponse,
  StatusResponse,
  PlatformAction,
  ActionResult,
  Agent,
  SubscriptionTier,
  SubscriptionStatus,
  ComponentEntry,
  ComponentManifest,
  WebSocketMessage,
  WebSocketResponse,
} from './types';
