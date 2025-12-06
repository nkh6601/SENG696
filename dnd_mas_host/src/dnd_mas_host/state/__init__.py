"""
State management module for D&D MAS Host system.

This module provides:
- HostState: Centralized state with nested structure (Blackboard pattern)
- BlackboardManager: Read/write access with configurable logging
- Action, Consequence: Structured types for game state updates
"""

from dnd_mas_host.state.host_state import (
    HostState,
    WorkflowState,
    GameContext,
    TurnState,
    OutputState,
    Action,
    Consequence,
    WorkflowStep,
    ActionType,
    ConsequenceType,
)
from dnd_mas_host.state.blackboard_manager import BlackboardManager

__all__ = [
    "HostState",
    "WorkflowState",
    "GameContext",
    "TurnState",
    "OutputState",
    "Action",
    "Consequence",
    "WorkflowStep",
    "ActionType",
    "ConsequenceType",
    "BlackboardManager",
]