"""
Data models for Interface Agent.

This module defines Pydantic models for structured data used by the
Interface Agent for conversation history and internal state management.
"""

from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


class ConversationEntry(BaseModel):
    """
    Single entry in conversation history.

    Attributes:
        speaker: Speaker name ("Narrator", "Player", NPC name, "System")
        text: Message content
        timestamp: ISO format timestamp
        entry_type: Type of entry ("narrative", "prompt", "system", "difficulty", "roll")
    """
    speaker: str = Field(description="Speaker name (Narrator/Player/NPC/System)")
    text: str = Field(description="Message content")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat(), description="ISO format timestamp")
    entry_type: str = Field(default="narrative", description="Entry type (narrative/prompt/system/difficulty/roll)")


class InterfaceState(BaseModel):
    """
    Internal state for Interface Agent.

    This tracks the GUI's internal state including game state display and thread
    coordination flags. Conversation history is now managed by GameState in GameManager.
    This is separate from HostState which tracks workflow coordination across all crews.
    """
    # Game state (synchronized from DISPLAY_NARRATIVE messages)
    campaign: str = Field(default="Humantown", description="Campaign name")
    player: str = Field(default="Adventurer", description="Player character name")
    player_class: str = Field(default="Fighter", description="Player character class")
    player_background: str = Field(default="", description="Player character background")
    character_hp: int = Field(default=20, description="Current HP")
    character_max_hp: int = Field(default=20, description="Maximum HP")
    current_stage: str = Field(default="", description="Current story stage")
    current_venue: str = Field(default="", description="Current location")

    # Character details (extended information)
    character_skills: List[str] = Field(default_factory=list, description="Character skill proficiencies")
    character_items: List[str] = Field(default_factory=list, description="Character inventory items")

    # NPC tracking
    active_npcs: List[dict] = Field(default_factory=list, description="NPCs in current venue with health")

    # Thread coordination
    flow_running: bool = Field(default=False, description="Whether HostFlow is currently executing")
    awaiting_difficulty_decision: bool = Field(default=False, description="Whether GUI is waiting for user difficulty decision")
    current_difficulty: Optional[int] = Field(default=None, description="Current difficulty DC if awaiting decision")
