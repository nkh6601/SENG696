"""
Interface package for D&D Multi-Agent System.

This package contains the GUI interface components that integrate
with the CrewAI HostFlow orchestration system.
"""

from .message_types import MessageType
from .interface_agent import InterfaceAgent
from .models import ConversationEntry, InterfaceState

__all__ = ["MessageType", "InterfaceAgent", "ConversationEntry", "InterfaceState"]
