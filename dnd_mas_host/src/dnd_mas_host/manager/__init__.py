"""
Manager module for D&D MAS Host system.

This module provides the HostManager - the backbone of the message-passing
architecture that owns the unified message queue, routes messages, and
kicks off agent execution.
"""

from dnd_mas_host.manager.host_manager import HostManager

__all__ = ["HostManager"]