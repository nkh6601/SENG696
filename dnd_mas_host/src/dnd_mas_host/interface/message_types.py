"""
Message types for agent-to-agent communication.

This module defines the message protocol used for the FIPA-inspired
message-passing architecture between agents (Interface, Narrator, Judge, NPC).
All messages flow through HostManager's unified queue.
"""

from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field
import time


class MessageType(str, Enum):
    """
    Message types for agent-to-agent communication.

    NOTE: HostManager is NOT a message sender/receiver except for NPC handling.
    Messages flow directly between Interface <-> Narrator <-> Judge <-> NPC.
    """

    # ========================================================================
    # Interface -> Narrator
    # ========================================================================
    VALIDATE_PROMPT = "validate_prompt"
    """User submitted a prompt that needs validation and action extraction."""

    # ========================================================================
    # Narrator -> Interface (validation failed)
    # ========================================================================
    VALIDATION_ERROR = "validation_error"
    """Prompt validation failed, ask user to rephrase."""

    # ========================================================================
    # Narrator -> Judge (validation success)
    # ========================================================================
    CHECK_FEASIBILITY = "check_feasibility"
    """Action extracted, request feasibility check and difficulty assignment."""

    # ========================================================================
    # Judge -> Interface (need roll)
    # ========================================================================
    REQUEST_DIFFICULTY_CHECK = "request_difficulty_check"
    """Difficulty assigned, request user to roll d20."""

    # ========================================================================
    # Judge -> Interface (action not feasible)
    # ========================================================================
    ACTION_INFEASIBLE = "action_infeasible"
    """Action is not feasible under D&D rules, ask for new prompt."""

    # ========================================================================
    # Interface -> Judge (after roll)
    # ========================================================================
    EVALUATE_CONSEQUENCE = "evaluate_consequence"
    """Roll completed, evaluate consequences based on result."""

    # ========================================================================
    # Judge -> NPC (after MC consequence evaluated)
    # ========================================================================
    EVALUATE_REACTIONS = "evaluate_reactions"
    """MC action resolved, NPCs should evaluate their reactions."""

    # ========================================================================
    # NPC processing (via HostManager) -> Judge
    # ========================================================================
    EVALUATE_NPC_CONSEQUENCE = "evaluate_npc_consequence"
    """Evaluate consequences for a specific NPC's reaction."""

    # ========================================================================
    # HostManager (after NPC loop) -> Narrator
    # ========================================================================
    GENERATE_NARRATIVE = "generate_narrative"
    """All actions resolved, generate narratives for MC and NPCs."""

    # ========================================================================
    # Narrator -> Interface (narrative ready)
    # ========================================================================
    DISPLAY_NARRATIVE = "display_narrative"
    """Narratives generated, display to user and update game state."""

    # ========================================================================
    # Error handling
    # ========================================================================
    FLOW_ERROR = "flow_error"
    """Unrecoverable error occurred, terminate turn gracefully."""

    # ========================================================================
    # GUI-specific messages (for InterfaceAgent internal use)
    # ========================================================================
    START_FLOW = "start_flow"
    """GUI: User clicked submit with a new prompt."""

    ROLL_D20 = "roll_d20"
    """GUI: User clicked roll button."""

    CANCEL_ACTION = "cancel_action"
    """GUI: User cancelled the current action."""

    SHUTDOWN = "shutdown"
    """GUI: Application shutdown requested."""

    FLOW_READY = "flow_ready"
    """GUI: Flow initialization complete, ready for prompts."""


class Message(BaseModel):
    """
    Message passed between agents via unified queue.

    This is the standard message format for all agent-to-agent communication.
    """
    to: str = Field(description="Recipient: Narrator, Judge, NPC, or Interface")
    type: MessageType = Field(description="Message type")
    data: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Message payload (type-specific data)"
    )
    from_agent: Optional[str] = Field(
        default=None,
        description="Sender agent name (for logging/debugging)"
    )
    timestamp: float = Field(
        default_factory=time.time,
        description="Unix timestamp when message was created"
    )

    class Config:
        arbitrary_types_allowed = True


def create_message(
    to: str,
    msg_type: MessageType,
    data: Optional[Dict[str, Any]] = None,
    from_agent: Optional[str] = None
) -> Message:
    """
    Helper to create standardized messages.

    Args:
        to: Recipient agent name ("Narrator", "Judge", "NPC", "Interface")
        msg_type: Type of message from MessageType enum
        data: Optional payload data
        from_agent: Optional sender name for logging

    Returns:
        Message object ready to be queued
    """
    return Message(
        to=to,
        type=msg_type,
        data=data or {},
        from_agent=from_agent
    )


def create_legacy_message(msg_type: MessageType, data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a legacy dict-based message (for backwards compatibility with existing GUI code).

    Args:
        msg_type: The type of message
        data: Message payload

    Returns:
        Formatted message dict with type, data, and timestamp
    """
    return {
        "type": msg_type,
        "data": data,
        "timestamp": time.time()
    }