/**
 * Type definitions for the 0pnMatrx SDK.
 */

/** Available AI agents */
export type Agent = 'trinity' | 'neo' | 'morpheus';

/** Subscription tier levels */
export type SubscriptionTier = 'free' | 'pro' | 'enterprise';

/** Chat request payload */
export interface ChatRequest {
  message: string;
  agent?: Agent;
  session_id?: string;
  wallet_connected?: boolean;
  network?: string;
  balance?: string;
  jurisdiction?: string;
}

/** Chat response from the gateway */
export interface ChatResponse {
  response: string;
  tool_calls: ToolCall[];
  session_id: string;
  agent: Agent;
  provider: string;
}

/** Tool call record */
export interface ToolCall {
  tool: string;
  arguments: Record<string, unknown>;
  result_preview?: string;
}

/** Server-Sent Event during streaming */
export interface StreamEvent {
  event: 'start' | 'token' | 'done' | 'error';
  data: Record<string, unknown>;
}

/** Health check response */
export interface HealthResponse {
  status: 'ok';
  agents: string[];
  model_provider: string;
  models: Record<string, unknown>;
}

/** Platform status response */
export interface StatusResponse {
  platform: string;
  version: string;
  agents: string[];
  model: {
    provider: string;
    primary: string;
  };
  sessions: number;
  wallet_sessions: number;
  total_requests: number;
  uptime_seconds: number;
  memory_mb: number;
  subsystems: Record<string, unknown>;
}

/** Platform action request */
export interface PlatformAction {
  action: string;
  params: Record<string, unknown>;
}

/** Platform action result */
export interface ActionResult {
  status: string;
  action: string;
  result: Record<string, unknown>;
}

/** Subscription status */
export interface SubscriptionStatus {
  tier: SubscriptionTier;
  usage: Record<string, { used: number; limit: number; remaining: number }>;
  is_trial: boolean;
  checkout_url?: string;
}

/** Component registry entry */
export interface ComponentEntry {
  id: string;
  name: string;
  description: string;
  category: string;
  min_tier: SubscriptionTier;
  limits: Record<string, Record<string, number>>;
  gateway_actions: string[];
  icon: string;
  available: boolean;
}

/** Component manifest */
export interface ComponentManifest {
  version: string;
  platform: string;
  components: ComponentEntry[];
}

/** WebSocket outgoing message */
export interface WebSocketMessage {
  type: 'chat';
  message: string;
  agent?: Agent;
  session_id?: string;
}

/** WebSocket incoming response */
export interface WebSocketResponse {
  type: 'token' | 'done' | 'error';
  text?: string;
  session_id?: string;
  agent?: string;
  provider?: string;
  tool_calls?: ToolCall[];
  error?: string;
}
