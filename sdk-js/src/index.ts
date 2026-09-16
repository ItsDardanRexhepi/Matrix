/**
 * The Matrix JavaScript/TypeScript SDK
 *
 * Provides a typed client for interacting with the Matrix gateway,
 * including chat, streaming, blockchain actions, and WebSocket connections.
 *
 * @example
 * ```typescript
 * import { MatrixClient } from '@the-matrix/sdk';
 *
 * const client = new MatrixClient('http://localhost:18790');
 * const response = await client.chat('What can you do?');
 * console.log(response.response);
 * ```
 */

export { MatrixClient } from './client';
export { MatrixStream } from './stream';
export { MatrixWebSocket } from './websocket';
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
