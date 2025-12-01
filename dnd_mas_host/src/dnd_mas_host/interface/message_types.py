"""
Message types and constants for GUI-Flow communication.

This module defines the message protocol used for thread-safe
communication between the PySimpleGUI interface and the CrewAI HostFlow.
"""

from enum import Enum
from typing import Any, Dict
import time


class MessageType(str, Enum):
    """Message types for GUI-Flow communication."""

    # GUI → Flow messages
    START_FLOW = "start_flow"
    ROLL_D20 = "roll_d20"
    CANCEL_ACTION = "cancel_action"
    SHUTDOWN = "shutdown"

    # Flow → GUI messages
    VALIDATION_ERROR = "validation_error"
    REQUEST_DIFFICULTY_CHECK = "request_difficulty_check"
    DISPLAY_NARRATIVE = "display_narrative"
    FLOW_ERROR = "flow_error"
    FLOW_READY = "flow_ready"


def create_message(msg_type: MessageType, data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a standardized message for queue communication.

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
