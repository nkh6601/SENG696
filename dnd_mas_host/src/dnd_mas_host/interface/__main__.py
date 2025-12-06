"""
Entry point for running the Interface Agent.

Usage:
    python -m dnd_mas_host.interface

This launches the V2 Interface Agent with the message-passing architecture.
"""

from dnd_mas_host.interface.interface_agent_v2 import main

if __name__ == "__main__":
    main()