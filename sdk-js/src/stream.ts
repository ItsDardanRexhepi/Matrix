/**
 * SSE stream handler for chat streaming responses.
 */

import type { StreamEvent } from './types';

export class OpenMatrixStream implements AsyncIterable<StreamEvent> {
  private response: Response;

  constructor(response: Response) {
    this.response = response;
  }

  async *[Symbol.asyncIterator](): AsyncIterator<StreamEvent> {
    const reader = this.response.body?.getReader();
    if (!reader) throw new Error('No response body');

    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        let currentEvent = '';
        let currentData = '';

        for (const line of lines) {
          if (line.startsWith('event: ')) {
            currentEvent = line.slice(7).trim();
          } else if (line.startsWith('data: ')) {
            currentData = line.slice(6).trim();
          } else if (line === '' && currentEvent && currentData) {
            try {
              yield {
                event: currentEvent as StreamEvent['event'],
                data: JSON.parse(currentData),
              };
            } catch {
              yield {
                event: currentEvent as StreamEvent['event'],
                data: { raw: currentData },
              };
            }
            currentEvent = '';
            currentData = '';
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  }

  /**
   * Collect all tokens into a single string.
   */
  async text(): Promise<string> {
    let result = '';
    for await (const event of this) {
      if (event.event === 'token' && event.data.text) {
        result += event.data.text;
      }
    }
    return result;
  }
}
