# @the-matrix/sdk

JavaScript/TypeScript SDK for the Matrix AI agent platform.

## Installation

```bash
npm install @the-matrix/sdk
```

## Quick Start

```typescript
import { MatrixClient } from '@the-matrix/sdk';

const client = new MatrixClient('http://localhost:18790');

// Chat with Trinity
const response = await client.chat('What can you do?');
console.log(response.response);

// Stream responses
const stream = await client.chatStream('Explain smart contracts');
for await (const event of stream) {
  if (event.event === 'token') {
    process.stdout.write(event.data.text);
  }
}
```

## API Reference

### `MatrixClient`

| Method | Description |
|--------|-------------|
| `chat(message, options?)` | Send a message, get a response |
| `chatStream(message, options?)` | Stream a response via SSE |
| `health()` | Check gateway health |
| `status()` | Get platform status |
| `readMemory(agent)` | Read agent memory |
| `writeMemory(agent, key, value)` | Write to agent memory |
| `getComponents()` | Get component registry |
| `subscriptionStatus()` | Get subscription status |
| `checkout(tier)` | Start checkout session |

### `MatrixWebSocket`

| Method | Description |
|--------|-------------|
| `connect()` | Connect to gateway |
| `send(message, options?)` | Send a chat message |
| `on(event, handler)` | Register event handler |
| `close()` | Close connection |

## License

MIT
