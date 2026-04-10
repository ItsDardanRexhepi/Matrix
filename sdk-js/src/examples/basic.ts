/**
 * Basic usage example for the 0pnMatrx SDK.
 */

import { OpenMatrixClient } from '../index';

async function main() {
  // Connect to the gateway
  const client = new OpenMatrixClient('http://localhost:18790');

  // Check health
  const health = await client.health();
  console.log('Gateway status:', health.status);
  console.log('Available agents:', health.agents);

  // Chat with Trinity
  const response = await client.chat('What blockchain services do you offer?');
  console.log('Trinity:', response.response);

  // Stream a response
  console.log('\nStreaming response:');
  const stream = await client.chatStream('Explain how DeFi loans work');
  for await (const event of stream) {
    if (event.event === 'token') {
      process.stdout.write(event.data.text as string);
    }
  }
  console.log('\n');

  // Get component registry
  const registry = await client.getComponents();
  console.log(`\n${registry.components.length} components available`);
  for (const comp of registry.components) {
    console.log(`  - ${comp.name} (${comp.min_tier})`);
  }
}

main().catch(console.error);
