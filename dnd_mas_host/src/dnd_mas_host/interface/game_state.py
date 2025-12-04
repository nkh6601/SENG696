"""
GameState model for persistent game state management.

This module defines the GameState model which tracks the entire game session
across multiple prompts. Unlike HostState which resets per prompt, GameState
persists throughout the campaign.
"""

from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime

from .character import Character


class ConversationTurn(BaseModel):
    """
    Single turn in conversation history.

    Captures the complete state of one prompt-response cycle including
    the player's prompt, the narrative output, HP changes, and location.
    """
    timestamp: datetime = Field(default_factory=datetime.now)
    prompt: str
    narrative: str
    hp_before: int
    hp_after: int
    venue: str
    stage: str


class GameState(BaseModel):
    """
    Persistent game state managed by GameManager.

    This tracks the entire game session across multiple prompts.
    Does NOT contain HostFlow workflow coordination fields (those are in HostState).

    Responsibilities:
    - Store player character data loaded from MongoDB
    - Track campaign progress (stage, venue, objectives)
    - Maintain conversation history across all prompts
    - Monitor win/loss conditions
    - Provide data for MongoDB persistence (save games)
    """
    # Campaign metadata
    campaign: str = "Humantown"
    save_id: Optional[str] = None  # MongoDB save game ID

    # Player Character (main character - Aldric)
    main_character: Optional[Character] = None

    # Companion characters (Jaylen, etc.)
    companions: List[Character] = Field(default_factory=list)

    # Campaign progress
    current_stage: str = ""
    current_venue: str = ""
    start_narrative: str = ""  # From stories.json, displayed once at game start

    # Objectives & progress
    main_objective: str = ""
    completed_objectives: List[str] = Field(default_factory=list)

    # Conversation history (persistent across prompts)
    conversation_history: List[ConversationTurn] = Field(default_factory=list)

    # Win/loss tracking
    game_over: bool = False
    victory: bool = False
    defeat_reason: Optional[str] = None

    # Session metadata
    session_start: datetime = Field(default_factory=datetime.now)
    last_saved: Optional[datetime] = None
    total_turns: int = 0

    def to_mongodb_dict(self) -> Dict[str, Any]:
        """
        Convert GameState to MongoDB document format.

        Returns:
            Dictionary suitable for MongoDB insertion
        """
        return {
            "save_id": self.save_id,
            "campaign": self.campaign,
            "main_character": self.main_character.to_dict() if self.main_character else None,
            "companions": [c.to_dict() for c in self.companions],
            "current_stage": self.current_stage,
            "current_venue": self.current_venue,
            "start_narrative": self.start_narrative,
            "main_objective": self.main_objective,
            "completed_objectives": self.completed_objectives,
            "conversation_history": [turn.model_dump() for turn in self.conversation_history],
            "game_over": self.game_over,
            "victory": self.victory,
            "defeat_reason": self.defeat_reason,
            "session_start": self.session_start,
            "last_saved": self.last_saved,
            "total_turns": self.total_turns
        }
