"""Fine-tuning data collection infrastructure for 0pnMatrx agents.

Captures conversation turns as potential training examples, supports
quality rating, and exports high-quality examples in JSONL format
suitable for Anthropic or OpenAI fine-tuning APIs.

Usage:
    collector = FinetuningCollector(db)
    await collector.initialize()
    await collector.record_example("trinity", user_msg, agent_response, tool_calls, session_id)
    await collector.rate_example(example_id, 5, flags=["excellent", "perfect_tone"])
    await collector.export_jsonl("trinity", "data/finetuning/trinity.jsonl")
"""

from runtime.finetuning.collector import FinetuningCollector

__all__ = ["FinetuningCollector"]
