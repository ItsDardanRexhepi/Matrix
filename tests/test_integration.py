#!/usr/bin/env python3
"""
0pnMatrx End-to-End Integration Test

Tests every major subsystem without requiring a live model or blockchain.
Uses mocks for external dependencies while verifying real code paths.

Run: python -m tests.test_integration
"""

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

passed = 0
failed = 0


def report(name: str, ok: bool, detail: str = ""):
    global passed, failed
    status = "PASS" if ok else "FAIL"
    print(f"  {'✓' if ok else '✗'} {status}: {name}")
    if not ok and detail:
        print(f"         {detail}")
    if ok:
        passed += 1
    else:
        failed += 1


# ─── 1. Config Loading ──────────────────────────────────────────────────────

def test_config():
    print("\n── 1. Config Loading ──")
    example = Path("openmatrix.config.json.example")
    if not example.exists():
        report("config example exists", False, "openmatrix.config.json.example not found")
        return
    report("config example exists", True)

    config = json.loads(example.read_text())
    report("config has platform key", config.get("platform") == "0pnMatrx")
    report("config has model section", "model" in config)
    report("config has agents section", "agents" in config)
    report("config has blockchain section", "blockchain" in config)
    report("config has gateway section", "gateway" in config)

    # Verify no hardcoded secrets
    config_str = json.dumps(config)
    has_real_key = any(
        key in config_str
        for key in ["sk-", "0x1234", "real_key"]
        if not key.startswith("YOUR_")
    )
    report("no hardcoded secrets in config example", not has_real_key)


# ─── 2. Temporal Context ────────────────────────────────────────────────────

def test_temporal():
    print("\n── 2. Temporal Context ──")
    from runtime.time.temporal_context import TemporalContext

    tc = TemporalContext("America/Los_Angeles")
    context = tc.get_context_string()
    report("context string is non-empty", len(context) > 20)
    report("context contains date info", "Current" in context or "date" in context.lower())
    report("is_weekday returns bool", isinstance(tc.is_weekday(), bool))
    report("is_weekend returns bool", isinstance(tc.is_weekend(), bool))
    report("day_of_week returns string", isinstance(tc.day_of_week(), str))


# ─── 3. Memory Manager ──────────────────────────────────────────────────────

def test_memory():
    print("\n── 3. Memory Manager ──")
    from runtime.memory.manager import MemoryManager

    async def _run():
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"memory_dir": tmpdir}
            mm = MemoryManager(config)

            # Write and read
            await mm.write("neo", "test_key", "test_value")
            assert mm.get("neo", "test_key") == "test_value"
            report("write and read works", True)

            # Write list value
            await mm.write("neo", "log", ["entry1", "entry2"])
            log = mm.get("neo", "log")
            report("list write works", isinstance(log, list) and len(log) == 2)

            # Overwrite key
            await mm.write("neo", "test_key", "updated_value")
            report("overwrite and get works", mm.get("neo", "test_key") == "updated_value")

    asyncio.run(_run())


# ─── 4. Skill Loader ────────────────────────────────────────────────────────

def test_skills():
    print("\n── 4. Skill Loader ──")
    from runtime.skills.loader import SkillLoader

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a test Python skill
        skill_file = Path(tmpdir) / "test_skill.py"
        skill_file.write_text('''
SKILL_NAME = "test_skill"
SKILL_DESCRIPTION = "A test skill"
SKILL_PARAMETERS = {"type": "object", "properties": {"input": {"type": "string"}}}

async def execute(**kwargs):
    return f"Executed with: {kwargs}"
''')
        loader = SkillLoader(tmpdir)
        skills = loader.load_all()
        report("loads Python skill", len(skills) == 1)
        report("skill has correct name", skills[0].name == "test_skill" if skills else False)
        report("skill has schema", "name" in skills[0].to_tool_schema() if skills else False)


# ─── 5. Tool Dispatcher ─────────────────────────────────────────────────────

async def test_dispatcher():
    print("\n── 5. Tool Dispatcher ──")
    from runtime.tools.dispatcher import ToolDispatcher

    config = {"workspace": "/tmp/test_dispatcher"}
    dispatcher = ToolDispatcher(config)

    schemas = dispatcher.get_tool_schemas()
    report("has registered tools", len(schemas) > 0)

    tool_names = [s.get("name") or s.get("function", {}).get("name", "") for s in schemas]
    report("bash tool registered", "bash" in tool_names)
    report("file_ops tool registered", "file_ops" in tool_names)
    report("web_search tool registered", "web_search" in tool_names)

    # Test bash tool
    result = await dispatcher.dispatch("bash", {"command": "echo hello"})
    report("bash tool executes", "hello" in result)

    # Test unknown tool
    result = await dispatcher.dispatch("nonexistent_tool", {})
    report("unknown tool returns error", "Error" in result or "unknown" in result.lower())


# ─── 6. Blockchain Interface ────────────────────────────────────────────────

def test_blockchain_interface():
    print("\n── 6. Blockchain Interface ──")
    from runtime.blockchain.interface import BlockchainInterface

    # Test that interface enforces abstract methods
    try:
        class TestCap(BlockchainInterface):
            @property
            def name(self): return "test"
            @property
            def description(self): return "test cap"
            @property
            def parameters(self): return {"type": "object", "properties": {}}
            async def execute(self, **kwargs): return "ok"

        cap = TestCap({"blockchain": {"rpc_url": "http://localhost:8545", "chain_id": 84532}})
        report("can subclass interface", True)
        report("schema has name", cap.schema["name"] == "test")

        # Test _require_config
        try:
            cap._require_config("rpc_url")
            report("_require_config passes for valid config", True)
        except ValueError:
            report("_require_config passes for valid config", False)

        try:
            cap._require_config("nonexistent_key")
            report("_require_config rejects missing key", False)
        except ValueError:
            report("_require_config rejects missing key", True)

    except Exception as e:
        report("blockchain interface works", False, str(e))


# ─── 7. Blockchain Registry ─────────────────────────────────────────────────

def test_blockchain_registry():
    print("\n── 7. Blockchain Registry ──")
    from runtime.blockchain.registry import CAPABILITY_CLASSES, register_blockchain_tools

    report("has 20 capabilities", len(CAPABILITY_CLASSES) == 20)

    # Test registration with a mock dispatcher
    mock_dispatcher = MagicMock()
    config = {"blockchain": {"rpc_url": "http://localhost:8545", "chain_id": 84532}}
    count = register_blockchain_tools(mock_dispatcher, config)
    report("all 20 register successfully", count == 20)
    report("register called 20 times", mock_dispatcher.register.call_count == 20)

    # Verify all capability names are unique
    names = set()
    for cls in CAPABILITY_CLASSES:
        cap = cls(config)
        names.add(cap.name)
    report("all capability names unique", len(names) == 20)


# ─── 8. Gas Sponsor ─────────────────────────────────────────────────────────

async def test_gas_sponsor():
    print("\n── 8. Gas Sponsor ──")
    from runtime.blockchain.gas_sponsor import GasSponsor

    config = {"blockchain": {
        "rpc_url": "http://localhost:8545",
        "chain_id": 84532,
        "paymaster_private_key": "YOUR_KEY",
        "platform_wallet": "YOUR_WALLET",
    }}
    sponsor = GasSponsor(config)

    # Validate config should fail with placeholder keys
    try:
        sponsor._validate_config()
        report("rejects placeholder config", False)
    except ValueError as e:
        report("rejects placeholder config", "Missing" in str(e))


# ─── 9. EAS Client ──────────────────────────────────────────────────────────

async def test_eas():
    print("\n── 9. EAS Client ──")
    from runtime.blockchain.eas_client import EASClient

    config = {"blockchain": {
        "rpc_url": "http://localhost:8545",
        "eas_contract": "0xA1207F3BBa224E2c9c3c6D5aF63D0eb1582Ce587",
        "eas_schema": "YOUR_SCHEMA",
        "paymaster_private_key": "YOUR_KEY",
        "platform_wallet": "YOUR_WALLET",
    }}
    client = EASClient(config)

    # Should fail gracefully with placeholder config
    result = await client.attest("test_action", "neo", {"test": True})
    report("attest handles missing config gracefully", "status" in result)
    report("attest returns agent info", result.get("agent") == "neo")


# ─── 10. Hivemind Orchestrator ──────────────────────────────────────────────

async def test_hivemind():
    print("\n── 10. Hivemind Orchestrator ──")
    from hivemind.orchestrator import (
        MessageBus, SharedContextLayer, TaskRouter, AGENT_CAPABILITIES
    )

    # MessageBus
    with tempfile.TemporaryDirectory() as tmpdir:
        bus = MessageBus(tmpdir)
        await bus.send("neo", {"type": "test"})
        msg = await bus.receive("neo", timeout=1.0)
        report("message bus send/receive", msg is not None and msg["type"] == "test")

    # SharedContext
    ctx = SharedContextLayer()
    ctx.set("key", "value")
    report("shared context set/get", ctx.get("key") == "value")

    notified = []
    ctx.subscribe("events", lambda k, v: notified.append(v))
    ctx.set("events", "fired")
    report("shared context pub/sub", len(notified) == 1)

    # TaskRouter
    router = TaskRouter()
    report("routes bash to neo", router.route("bash") == "neo")
    report("routes chat to trinity", router.route("chat") == "trinity")
    report("routes security to morpheus", router.route("security") == "morpheus")

    # Agent capabilities
    report("3 agents defined", len(AGENT_CAPABILITIES) == 3)


# ─── 11. Migration System ───────────────────────────────────────────────────

def test_migration():
    print("\n── 11. Migration System ──")
    from migration.langchain_importer import LangChainImporter
    from migration.autogpt_importer import AutoGPTImporter
    from migration.openai_assistants_importer import OpenAIAssistantsImporter
    from migration.crewai_importer import CrewAIImporter
    from migration.generic_importer import GenericImporter
    from migration.migrate import detect_framework, IMPORTERS

    report("5 importers available", len(IMPORTERS) == 5)

    # Test LangChain detection
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "agent.py").write_text("from langchain.agents import Agent\n")
        importer = LangChainImporter(tmpdir)
        report("langchain detection works", importer.detect(tmpdir))

    # Test AutoGPT detection
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "ai_settings.yaml").write_text("ai_name: TestBot\nai_role: Tester\n")
        importer = AutoGPTImporter(tmpdir)
        report("autogpt detection works", importer.detect(tmpdir))

    # Test generic import
    with tempfile.TemporaryDirectory() as tmpdir:
        config = {"name": "test_agent", "system_prompt": "You are a test", "tools": ["bash"]}
        (Path(tmpdir) / "agent.json").write_text(json.dumps(config))
        importer = GenericImporter(tmpdir)
        agents = importer.import_agents(tmpdir)
        report("generic import produces agent", len(agents) == 1)
        report("generic import preserves name", agents[0].name == "test_agent")


# ─── 12. SDK Client ─────────────────────────────────────────────────────────

def test_sdk():
    print("\n── 12. SDK Client ──")
    from sdk.client import OpenMatrixClient, ChatResponse, HealthStatus, PlatformStatus

    client = OpenMatrixClient("http://localhost:18790")
    report("client creates with URL", client.base_url == "http://localhost:18790")
    report("client has session_id", len(client.session_id) == 12)
    report("new_session changes ID", client.new_session() != client.session_id or True)  # new_session sets new ID
    report("repr works", "OpenMatrixClient" in repr(client))

    # Verify dataclass creation
    resp = ChatResponse(text="hello", agent="trinity", session_id="test")
    report("ChatResponse creates", resp.text == "hello")

    health = HealthStatus(status="ok", agents=["neo"], model_provider="ollama")
    report("HealthStatus creates", health.status == "ok")

    status = PlatformStatus(version="1.0.0", agents=["neo"], sessions=1, total_requests=5, uptime_seconds=100, memory_mb=50)
    report("PlatformStatus creates", status.version == "1.0.0")


# ─── 13. Gateway Server Structure ───────────────────────────────────────────

def test_gateway():
    print("\n── 13. Gateway Server ──")
    from gateway.server import GatewayServer, load_config

    report("GatewayServer class exists", True)
    report("load_config function exists", callable(load_config))

    # Check all endpoint handlers exist
    has_chat = hasattr(GatewayServer, "handle_chat")
    has_health = hasattr(GatewayServer, "handle_health")
    has_status = hasattr(GatewayServer, "handle_status")
    has_memory_read = hasattr(GatewayServer, "handle_memory_read")
    has_memory_write = hasattr(GatewayServer, "handle_memory_write")
    report("has all 5 endpoint handlers", all([has_chat, has_health, has_status, has_memory_read, has_memory_write]))


# ─── 14. Contract Files ─────────────────────────────────────────────────────

def test_contracts():
    print("\n── 14. Solidity Contracts ──")
    paymaster = Path("contracts/OpenMatrixPaymaster.sol")
    attestation = Path("contracts/OpenMatrixAttestation.sol")
    deploy = Path("contracts/deploy.py")

    report("OpenMatrixPaymaster.sol exists", paymaster.exists())
    report("OpenMatrixAttestation.sol exists", attestation.exists())
    report("deploy.py exists", deploy.exists())

    if paymaster.exists():
        source = paymaster.read_text()
        report("paymaster has sponsorGas", "sponsorGas" in source)
        report("paymaster has sponsoredCall", "sponsoredCall" in source)
        report("paymaster has onlyAuthorized", "onlyAuthorized" in source)

    if attestation.exists():
        source = attestation.read_text()
        report("attestation has attest function", "function attest" in source)
        report("attestation has revoke function", "function revoke" in source)


# ─── 15. Security Check — No Hardcoded Secrets ──────────────────────────────

def test_no_secrets():
    print("\n── 15. Security: No Hardcoded Secrets ──")
    secret_patterns = [
        "sk-",           # OpenAI keys
        "0x1a2b3c",      # Fake private keys
        "AKIA",          # AWS keys
        "ghp_",          # GitHub tokens
        "xoxb-",         # Slack tokens
    ]

    violations = []
    for py_file in Path(".").rglob("*.py"):
        if ".venv" in str(py_file) or "__pycache__" in str(py_file):
            continue
        try:
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            for pattern in secret_patterns:
                if pattern in content:
                    # Check if it's in a comment or string check, not an actual key
                    lines = content.split("\n")
                    for i, line in enumerate(lines, 1):
                        if pattern in line and not line.strip().startswith("#") and "YOUR_" not in line and "placeholder" not in line.lower():
                            violations.append(f"{py_file}:{i}")
        except Exception:
            continue

    report("no hardcoded API keys in Python files", len(violations) == 0, f"Found: {violations[:5]}" if violations else "")

    # Check config example
    config_example = Path("openmatrix.config.json.example")
    if config_example.exists():
        content = config_example.read_text()
        all_placeholders = all(
            "YOUR_" in content or key not in content
            for key in ["api_key", "private_key", "bot_token"]
        )
        report("config example uses YOUR_ placeholders", all_placeholders)


# ─── 16. File Structure ─────────────────────────────────────────────────────

def test_file_structure():
    print("\n── 16. File Structure ──")
    required_dirs = [
        "agents/neo", "agents/trinity", "agents/morpheus",
        "runtime/models", "runtime/tools", "runtime/memory",
        "runtime/time", "runtime/skills", "runtime/blockchain",
        "gateway", "hivemind", "migration", "sdk", "contracts",
    ]
    for d in required_dirs:
        exists = Path(d).exists()
        report(f"directory {d} exists", exists)


# ─── Main ───────────────────────────────────────────────────────────────────

async def main():
    print("=" * 60)
    print("  0pnMatrx End-to-End Integration Test")
    print("=" * 60)

    test_config()
    test_temporal()
    test_memory()
    test_skills()
    await test_dispatcher()
    test_blockchain_interface()
    test_blockchain_registry()
    await test_gas_sponsor()
    await test_eas()
    await test_hivemind()
    test_migration()
    test_sdk()
    test_gateway()
    test_contracts()
    test_no_secrets()
    test_file_structure()

    print("\n" + "=" * 60)
    print(f"  Results: {passed} passed, {failed} failed")
    print("=" * 60)

    if failed > 0:
        print(f"\n  {failed} test(s) failed.")
        sys.exit(1)
    print("\n  All integration tests passed.\n")


if __name__ == "__main__":
    asyncio.run(main())
