"""
Host State module for D&D MAS Host system.

This module defines the centralized HostState with nested structure (Blackboard pattern),
along with Action and Consequence classes for type-safe game state updates.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum


# ============================================================================
# Enums
# ============================================================================

class WorkflowStep(str, Enum):
    """Workflow steps for tracking progress."""
    STEP_1_RECEIVE_PROMPT = "1_receive_prompt"
    STEP_2_VALIDATE_PROMPT = "2_validate_prompt"
    STEP_3_CHECK_DIFFICULTY = "3_check_difficulty"
    STEP_4_REQUEST_ROLL = "4_request_roll"
    STEP_5_PERFORM_CHECK = "5_perform_check"
    STEP_6_EVALUATE_CONSEQUENCE = "6_evaluate_consequence"
    STEP_7_EVALUATE_REACTIONS = "7_evaluate_reactions"
    STEP_8_GENERATE_NARRATIVE = "8_generate_narrative"
    STEP_9_DISPLAY_OUTPUT = "9_display_output"
    ERROR = "error"


class ActionType(str, Enum):
    """Types of actions characters can perform."""
    ATTACK = "attack"
    MOVE = "move"
    CAST_SPELL = "cast_spell"
    INVESTIGATE = "investigate"
    PERSUADE = "persuade"
    INTIMIDATE = "intimidate"
    DECEIVE = "deceive"
    STEALTH = "stealth"
    INTERACT = "interact"
    OTHER = "other"


class ConsequenceType(str, Enum):
    """Types of consequences from actions."""
    DAMAGE = "damage"
    HEALING = "healing"
    MOVEMENT = "movement"
    STATUS_EFFECT = "status_effect"
    ITEM_CHANGE = "item_change"
    VENUE_CHANGE = "venue_change"
    STAGE_CHANGE = "stage_change"
    NPC_STATE_CHANGE = "npc_state_change"
    ENVIRONMENTAL = "environmental"


# ============================================================================
# Action & Consequence Classes
# ============================================================================

class Action(BaseModel):
    """Structured representation of an action."""
    action_type: ActionType = Field(description="Type of action")
    actor_name: str = Field(description="Name of character performing the action")
    target: Optional[str] = Field(default=None, description="Target name (Character, Venue, or object)")
    method: str = Field(default="", description="How the action is performed (e.g., 'with longsword', 'using Fireball')")
    intent: str = Field(default="", description="Why the action is performed (e.g., 'to defeat the slime')")
    difficulty: Optional[int] = Field(default=None, description="DC assigned by Judge (1-21, or -1 for auto-fail)")

    class Config:
        arbitrary_types_allowed = True


class Consequence(BaseModel):
    """Structured representation of a consequence."""
    consequence_type: ConsequenceType = Field(description="Type of consequence")
    target_name: str = Field(description="Name of target affected by consequence")
    description: str = Field(description="Human-readable description of consequence")

    # Type-specific fields (conditionally required)
    # DAMAGE
    damage_amount: Optional[int] = Field(default=None, description="Amount of damage dealt")
    damage_type: Optional[str] = Field(default=None, description="Type of damage (slashing, fire, etc.)")

    # HEALING
    healing_amount: Optional[int] = Field(default=None, description="Amount of HP restored")

    # MOVEMENT
    new_location: Optional[str] = Field(default=None, description="New venue/stage name")

    # STATUS_EFFECT
    status_effect: Optional[str] = Field(default=None, description="Status effect applied (poisoned, stunned, etc.)")
    duration: Optional[int] = Field(default=None, description="Duration in turns")

    # ITEM_CHANGE
    item_gained: Optional[str] = Field(default=None, description="Item added to inventory")
    item_lost: Optional[str] = Field(default=None, description="Item removed from inventory")

    # NPC_STATE_CHANGE
    npc_state_change: Optional[Dict[str, Any]] = Field(default=None, description="Changes to NPC state (e.g., attitude, intentions)")

    class Config:
        arbitrary_types_allowed = True


# ============================================================================
# Nested State Sections
# ============================================================================

class WorkflowState(BaseModel):
    """Workflow coordination state."""
    current_step: WorkflowStep = Field(
        default=WorkflowStep.STEP_1_RECEIVE_PROMPT,
        description="Current workflow step"
    )
    current_agent: str = Field(default="", description="Name of agent currently processing")
    flow_complete: bool = Field(default=False, description="Whether the turn is complete")

    # Error handling
    error_log: List[Dict[str, str]] = Field(
        default_factory=list,
        description="List of errors encountered"
    )
    retry_count: Dict[str, int] = Field(
        default_factory=dict,
        description="Retry count per agent (e.g., {'Narrator': 1})"
    )
    pipeline_branch: str = Field(default="success", description="Current branch (success, failed, retry)")


class GameContext(BaseModel):
    """
    Immutable game context (loaded at initialization).

    Note: This uses string references and dictionaries to avoid circular imports.
    The actual Character, Campaign, Stage, Venue objects are managed by GameManager.
    """
    campaign_name: str = Field(description="Campaign name")
    campaign_objective: str = Field(default="", description="Campaign objective/win condition")
    campaign_outline: str = Field(default="", description="Story outline")

    main_character_name: str = Field(description="Player's main character name")
    companion_names: List[str] = Field(default_factory=list, description="Companion character names")

    current_stage_name: str = Field(description="Current stage name")
    current_venue_name: str = Field(description="Current venue name")

    # Full data dictionaries (loaded from MongoDB)
    all_stages: Dict[str, Any] = Field(
        default_factory=dict,
        description="All stages keyed by stage name"
    )
    all_venues: Dict[str, Any] = Field(
        default_factory=dict,
        description="All venues keyed by venue name"
    )
    all_npcs: Dict[str, Any] = Field(
        default_factory=dict,
        description="All NPCs across campaign keyed by name"
    )
    all_characters: Dict[str, Any] = Field(
        default_factory=dict,
        description="All characters (MC + companions) keyed by name"
    )

    class Config:
        arbitrary_types_allowed = True


class TurnState(BaseModel):
    """Current turn state (reset per prompt)."""
    # Prompt processing
    prompt_text: str = Field(default="", description="User's input prompt")
    prompt_valid: bool = Field(default=True, description="Whether prompt passed validation")
    validation_message: Optional[str] = Field(default=None, description="Validation error message")

    # Action processing
    action_extracted: Optional[Action] = Field(default=None, description="Extracted action from prompt")
    difficulty_check: int = Field(default=0, description="d20 roll result (1-20)")
    skip_difficulty_check: bool = Field(default=False, description="Whether to skip roll (auto-success/fail)")
    mc_consequence: List[Consequence] = Field(
        default_factory=list,
        description="Main character action consequences"
    )

    # NPC reactions
    active_npc_names: List[str] = Field(
        default_factory=list,
        description="NPC names in current venue (updated before NPC processing)"
    )
    reactions_list: Dict[str, Action] = Field(
        default_factory=dict,
        description="NPC reactions keyed by character name"
    )
    reactions_consequence_list: Dict[str, List[Consequence]] = Field(
        default_factory=dict,
        description="NPC reaction consequences keyed by character name"
    )

    class Config:
        arbitrary_types_allowed = True


class OutputState(BaseModel):
    """Output state for narratives."""
    final_output: Dict[str, str] = Field(
        default_factory=dict,
        description="Final narratives keyed by character name (MC + NPCs)"
    )

    # Context from previous turn
    previous_prompt: str = Field(default="", description="Previous prompt for context")
    previous_narrative: str = Field(default="", description="Previous narrative for context")


# ============================================================================
# Root HostState
# ============================================================================

class HostState(BaseModel):
    """
    Root state object for the D&D MAS system (Blackboard pattern).

    Nested structure:
    - workflow: Workflow coordination (step, agent, errors)
    - game_context: Immutable game data (campaign, characters, venues)
    - current_turn: Turn-specific data (prompt, action, consequences)
    - output: Narrative outputs
    """
    workflow: WorkflowState = Field(
        default_factory=WorkflowState,
        description="Workflow coordination state"
    )
    game_context: GameContext = Field(description="Immutable game context")
    current_turn: TurnState = Field(
        default_factory=TurnState,
        description="Current turn state"
    )
    output: OutputState = Field(
        default_factory=OutputState,
        description="Output narratives"
    )

    class Config:
        arbitrary_types_allowed = True