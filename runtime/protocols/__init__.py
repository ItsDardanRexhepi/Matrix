"""
Agent Protocol Stack — Cognitive protocols for intelligent agents.

These protocols transform Neo, Trinity, and Morpheus from chat wrappers
into reasoning, planning, pattern-detecting agents with persistent identity.
"""

from runtime.protocols.jarvis import JarvisProtocol
from runtime.protocols.ultron import UltronProtocol
from runtime.protocols.friday import FridayProtocol
from runtime.protocols.vision import VisionProtocol
from runtime.protocols.omega import OmegaMind
from runtime.protocols.trajectory import TrajectoryEngine
from runtime.protocols.outcome_learning import OutcomeLearning
from runtime.protocols.morpheus_triggers import MorpheusTriggerSystem
from runtime.protocols.rexhepi_gate import RexhepiGate
from runtime.protocols.integration import ProtocolStack
from runtime.protocols.omniversal import OmniversalProtocol
from runtime.protocols.hivemind import HiveMindProtocol
from runtime.protocols.conversational import ConversationalLayer
from runtime.protocols.outcome_schema import (
    OutcomeSchema,
    OutcomeLinker,
    ReplayEngine,
    LearningStore,
)

__all__ = [
    "JarvisProtocol",
    "UltronProtocol",
    "FridayProtocol",
    "VisionProtocol",
    "OmegaMind",
    "TrajectoryEngine",
    "OutcomeLearning",
    "MorpheusTriggerSystem",
    "RexhepiGate",
    "ProtocolStack",
    "OmniversalProtocol",
    "HiveMindProtocol",
    "ConversationalLayer",
    "OutcomeSchema",
    "OutcomeLinker",
    "ReplayEngine",
    "LearningStore",
]
