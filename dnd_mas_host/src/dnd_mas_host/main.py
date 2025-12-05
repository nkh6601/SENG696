#!/usr/bin/env python
from datetime import time
from random import randint
from typing import List, Dict, Optional, Any
from enum import Enum
import queue

from pydantic import BaseModel, Field

from crewai.flow.flow import Flow, listen, start, router

from dnd_mas_host.crews.judge_crew.judge_crew import JudgeFlow

from dnd_mas_host.crews.narrator_crew.narrator_crew import NarratorFlow

from dnd_mas_host.crews.npc_crew.npc_crew import NpcCrew

from dnd_mas_host.interface.character import Character
from dnd_mas_host.interface.models import Venue, Stage


# Custom exceptions for GUI integration
class UserCancelledActionException(Exception):
    """Raised when user cancels action during difficulty check"""
    pass


class FlowShutdownException(Exception):
    """Raised when flow should terminate cleanly"""
    pass


class WorkflowStep(str, Enum):
    """12-step game loop + 3 exception paths"""
    # Main workflow steps (1-12)
    STEP_1_RECEIVE_PROMPT = "step_1_receive_prompt"
    STEP_2_VALIDATE_PROMPT = "step_2_validate_prompt"
    STEP_3_EXTRACT_ACTION = "step_3_extract_action"
    STEP_4_EVALUATE_DIFFICULTY = "step_4_evaluate_difficulty"
    STEP_5_PERFORM_CHECK = "step_5_perform_check"
    STEP_6_EVALUATE_CONSEQUENCES = "step_6_evaluate_consequences"
    STEP_6_1_EVALUATE_CONSEQUENCES_COMPLETE = "step_6_1_evaluate_consequences_complete"
    STEP_7_EVALUATE_NPC_REACTIONS = "step_7_evaluate_npc_reactions"
    STEP_8_NPC_DIFFICULTY_CHECK = "step_8_npc_difficulty_check"
    STEP_9_NPC_CONSEQUENCES = "step_9_npc_consequences"
    STEP_10_GENERATE_NARRATIVE = "step_10_generate_narrative"
    STEP_11_DISPLAY_OUTPUT = "step_11_display_output"
    STEP_12_AWAIT_NEXT_PROMPT = "step_12_await_next_prompt"

    # Exception paths
    EXCEPTION_INVALID_PROMPT = "exception_invalid_prompt"
    EXCEPTION_SKIP_DIFFICULTY_CHECK = "exception_skip_difficulty_check"
    EXCEPTION_NO_NPC_REACTIONS = "exception_no_npc_reactions"


class HostState(BaseModel):
    """
    Workflow coordination state for HostFlow.

    Reset before each prompt execution. Synced from/to GameState by GameManager.
    This only contains workflow coordination fields, not persistent game state.
    """
    # Workflow coordination (reset per prompt)
    workflow_step: WorkflowStep = Field(default=WorkflowStep.STEP_1_RECEIVE_PROMPT, description="Current step in the game loop")
    current_agent: str = Field(default="", description="Name of the agent currently processing")
    flow_complete: bool = Field(default=False, description="Flag to indicate flow completion (for debugging)")

    # Current prompt processing
    prompt_text: str = Field(default="", description="Current user's prompt being processed")
    prompt_valid: bool = Field(default=True, description="Whether the prompt passed validation")
    validation_message: Optional[str] = Field(default=None, description="Validation feedback message if prompt is invalid")

    # Action processing (current turn)
    action_extracted: Optional[Dict[str, Any]] = Field(default=None, description="Extracted action (action_type, target, method, intent)")
    Action_difficulty: Dict[str, int] = Field(default_factory=dict, description="Action difficulty assigned by Judge Agent")
    difficulty_check: int = Field(default=0, description="The d20 roll result for difficulty check")
    skip_difficulty_check: bool = Field(default=False, description="Whether to skip difficulty check (too easy/impossible)")
    effect: Optional[str] = Field(default=None, description="The effect of action evaluated by Judge Agent")

    # NPC reactions (current turn)
    active_npcs: List[Character] = Field(default_factory=list, description="NPCs in current venue (loaded by GameManager)")
    reactions_list: Dict[Character, Any] = Field(default_factory=list, description="List of completed NPC reactions with narratives")

    # Output (current turn)
    final_output: str = Field(default="", description="Final generated narrative to display to user")

    # Game state snapshot (synced from GameState before kickoff) - now using Character class
    campaign: str = Field(default="Humantown", description="Campaign name")
    main_character: Optional[Character] = Field(default=None, description="Main character (Player Character)")
    companions: List[Character] = Field(default_factory=list, description="Companion characters")
    current_stage: str = Field(default="", description="Current story stage")
    current_venue: str = Field(default="", description="Current location/venue")

    # NEW: Structured objects for enriched context (loaded from MongoDB)
    current_stage_obj: Optional[Stage] = Field(default=None, description="Full stage object with venues and descriptions")
    current_venue_obj: Optional[Venue] = Field(default=None, description="Full venue object with environment, NPCs, connections")
    active_npcs_detailed: List[Character] = Field(default_factory=list, description="Detailed NPC list for current venue")

    # Context from previous turn
    previous_prompt: str = Field(default="", description="Previous user prompt for context")
    previous_narrative: str = Field(default="", description="Previous narrative output for context")



class HostFlow(Flow[HostState]):
    """
    D&D MAS 12-step game loop orchestration using CrewAI Flow.

    This flow coordinates 3 crews (Narrator, Judge, NPC) through the complete
    game loop with conditional branching based on validation and difficulty checks.
    """

    def __init__(self, gui_queues: Optional[Dict[str, queue.Queue]] = None):
        """
        Initialize HostFlow (created once, reused for all prompts).

        Args:
            gui_queues: Optional dict with 'to_flow' and 'from_flow' queues for GUI integration
        """
        super().__init__()
        self.gui_queues = gui_queues

    def reset_state(self):
        """
        Reset workflow coordination fields before new prompt.

        Resets:
        - workflow_step → STEP_1_RECEIVE_PROMPT
        - current_agent → ""
        - flow_complete → False
        - prompt_text, action_extracted, difficulty_check, etc. → defaults
        - final_output → ""
        - active_npcs, reactions_list → []

        Preserves (synced from GameState by GameManager):
        - campaign, main_character, companions, current_stage, current_venue
        - previous_prompt, previous_narrative
        """
        self.state.workflow_step = WorkflowStep.STEP_1_RECEIVE_PROMPT
        self.state.current_agent = ""
        self.state.flow_complete = False
        self.state.prompt_text = ""
        self.state.prompt_valid = True
        self.state.validation_message = None
        self.state.action_extracted = None
        self.state.Action_difficulty = {}
        self.state.difficulty_check = 0
        self.state.skip_difficulty_check = False
        self.state.effect = None
        self.state.active_npcs = []
        self.state.reactions_list = []
        self.state.final_output = ""

    def _load_venue_from_db(self, venue_name: str) -> Optional[Venue]:
        """
        Load venue object from MongoDB.

        Args:
            venue_name: Name of the venue to load

        Returns:
            Venue object if found, None otherwise
        """
        print(f"[DEBUG] _load_venue_from_db called with venue_name='{venue_name}'")
        try:
            from pymongo import MongoClient
            from dnd_mas_host.tools.mongodb_vector_tools import MongoDBVectorSearchConfig

            print(f"[DEBUG] Connecting to MongoDB: {MongoDBVectorSearchConfig.MONGO_URI}")
            client = MongoClient(MongoDBVectorSearchConfig.MONGO_URI)
            db = client["campaign"]

            print(f"[DEBUG] Searching for venue with name='{venue_name}'")
            venue_doc = db["venues"].find_one({"name": venue_name})

            if venue_doc:
                print(f"[DEBUG] Found venue document: {list(venue_doc.keys())}")

                # Extract action names from action objects
                # MongoDB stores: [{"name": "...", "description": "..."}, ...]
                # Model expects: ["action_name1", "action_name2", ...]
                actions = venue_doc.get("actions", [])
                action_names = []
                if actions:
                    for action in actions:
                        if isinstance(action, dict):
                            action_names.append(action.get("name", ""))
                        else:
                            action_names.append(str(action))
                print(f"[DEBUG] Extracted {len(action_names)} action names: {action_names}")

                venue = Venue(
                    name=venue_doc.get("name", ""),
                    env_desc=venue_doc.get("envDesc", ""),
                    story_desc=venue_doc.get("storyDesc", ""),
                    connect_venues=venue_doc.get("connectVenues", []),
                    npcs_present=venue_doc.get("NPCs", []),
                    supported_actions=action_names
                )
                print(f"[DEBUG] Successfully created Venue object: {venue.name}")
                return venue
            else:
                print(f"[DEBUG] No venue found with name='{venue_name}'")
                return None
        except Exception as e:
            print(f"[ERROR] Failed to load venue {venue_name}: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _load_stage_from_db(self, stage_name: str) -> Optional[Stage]:
        """
        Load stage object from MongoDB.

        Args:
            stage_name: Name of the stage to load

        Returns:
            Stage object if found, None otherwise
        """
        print(f"[DEBUG] _load_stage_from_db called with stage_name='{stage_name}'")
        try:
            from pymongo import MongoClient
            from dnd_mas_host.tools.mongodb_vector_tools import MongoDBVectorSearchConfig

            print(f"[DEBUG] Connecting to MongoDB: {MongoDBVectorSearchConfig.MONGO_URI}")
            client = MongoClient(MongoDBVectorSearchConfig.MONGO_URI)
            db = client["campaign"]

            print(f"[DEBUG] Searching for stage with name='{stage_name}'")
            stage_doc = db["stages"].find_one({"name": stage_name})

            if stage_doc:
                print(f"[DEBUG] Found stage document: {list(stage_doc.keys())}")
                stage = Stage(
                    name=stage_doc.get("name", ""),
                    env_desc=stage_doc.get("envDesc", ""),
                    story_desc=stage_doc.get("storyDesc", ""),
                    venues=stage_doc.get("venues", []),
                    start_venue=stage_doc.get("start_venue", ""),
                    start_narrative=stage_doc.get("start_narrative", "")
                )
                print(f"[DEBUG] Successfully created Stage object: {stage.name}")
                return stage
            else:
                print(f"[DEBUG] No stage found with name='{stage_name}'")
                return None
        except Exception as e:
            print(f"[ERROR] Failed to load stage {stage_name}: {e}")
            import traceback
            traceback.print_exc()
            return None

    def load_enriched_context(self):
        """
        Load enriched venue and stage objects from MongoDB.

        This method is called after HostState has been synced from GameState
        to populate the structured object fields for use by sub-flows.
        """
        print(f"\n[DEBUG] ========== load_enriched_context() START ==========")
        print(f"[DEBUG] Current state values:")
        print(f"[DEBUG]   - current_venue: '{self.state.current_venue}'")
        print(f"[DEBUG]   - current_stage: '{self.state.current_stage}'")
        print(f"[DEBUG]   - active_npcs count: {len(self.state.active_npcs)}")

        # Load venue object
        if self.state.current_venue:
            print(f"[DEBUG] Loading venue '{self.state.current_venue}'...")
            self.state.current_venue_obj = self._load_venue_from_db(self.state.current_venue)
            if self.state.current_venue_obj:
                print(f"[INFO] ✓ Loaded venue: {self.state.current_venue_obj.name}")
            else:
                print(f"[WARNING] ✗ Failed to load venue: {self.state.current_venue}")
        else:
            print(f"[WARNING] current_venue is empty - skipping venue load")

        # Load stage object
        if self.state.current_stage:
            print(f"[DEBUG] Loading stage '{self.state.current_stage}'...")
            self.state.current_stage_obj = self._load_stage_from_db(self.state.current_stage)
            if self.state.current_stage_obj:
                print(f"[INFO] ✓ Loaded stage: {self.state.current_stage_obj.name}")
            else:
                print(f"[WARNING] ✗ Failed to load stage: {self.state.current_stage}")
        else:
            print(f"[WARNING] current_stage is empty - skipping stage load")

        # Copy active_npcs to active_npcs_detailed (already Character objects)
        self.state.active_npcs_detailed = self.state.active_npcs
        print(f"[DEBUG] Copied {len(self.state.active_npcs_detailed)} NPCs to active_npcs_detailed")
        print(f"[DEBUG] ========== load_enriched_context() END ==========\n")

    @start()
    def receive_prompt(self):
        """Step 1: Interface receives user input"""
        self.state.workflow_step = WorkflowStep.STEP_1_RECEIVE_PROMPT
        self.state.current_agent = "Interface"
        # self.state.prompt_text should be set before kickoff
        return self.state

    @listen(receive_prompt)
    async def validate_and_extract(self):
        """Steps 2-3: Narrator validates + extracts using NarratorFlow"""
        print(f"\n[DEBUG] HostFlow.validate_and_extract() called")
        print(f"[DEBUG]   - prompt_text: '{self.state.prompt_text[:50] if self.state.prompt_text else None}...'")
        print(f"[DEBUG]   - current_venue: {self.state.current_venue}")

        self.state.workflow_step = WorkflowStep.STEP_2_VALIDATE_PROMPT
        self.state.current_agent = "Narrator"

        # Create and run NarratorFlow (validation phase) - async call
        narrator_flow = NarratorFlow()

        # Create and inject GameStateSearchTool into all agent tool lists
        from dnd_mas_host.tools.mongodb_vector_tools import GameStateSearchTool
        game_state_tool = GameStateSearchTool(self.state)
        #for agent_name in narrator_flow.tools:
            #narrator_flow.tools[agent_name].append(game_state_tool)

        print(f"[DEBUG] Calling narrator_flow.kickoff_async()...")

        await narrator_flow.kickoff_async(inputs={
            "campaign": self.state.campaign,
            "player": self.state.main_character.name if self.state.main_character else "",
            "prompt": self.state.prompt_text,
            "current_venue": self.state.current_venue,  # Keep for backward compat
            "current_venue_obj": self.state.current_venue_obj.model_dump() if self.state.current_venue_obj else None,
            "current_stage_obj": self.state.current_stage_obj.model_dump() if self.state.current_stage_obj else None,
            "active_npcs": [npc.model_dump() for npc in self.state.active_npcs_detailed],
            "player_character": self.state.main_character.model_dump() if self.state.main_character else None
        })

        # DEBUG: Check narrator flow final state
        print(f"[DEBUG] NarratorFlow completed!")
        print(f"[DEBUG]   - prompt_valid: {narrator_flow.state.prompt_valid}")
        print(f"[DEBUG]   - validation_message: '{narrator_flow.state.validation_message[:100] if narrator_flow.state.validation_message else None}...'")
        print(f"[DEBUG]   - action_extracted: {narrator_flow.state.action_extracted}")

        # Extract results from flow state
        self.state.prompt_valid = narrator_flow.state.prompt_valid
        self.state.validation_message = narrator_flow.state.validation_message
        self.state.action_extracted = narrator_flow.state.action_extracted

        print(f"[DEBUG] HostState updated:")
        print(f"[DEBUG]   - prompt_valid: {self.state.prompt_valid}")

        return self.state

    @router(validate_and_extract)
    def route_validation(self):
        """Route based on prompt validation"""
        print(f"\n[DEBUG] HostFlow.route_validation() called")
        print(f"[DEBUG]   - prompt_valid: {self.state.prompt_valid}")

        if self.state.prompt_valid:
            print("[DEBUG] Routing to check_difficulty")
            return "check_difficulty"
        else:
            print("[DEBUG] Validation failed - sending error to GUI and terminating flow")

            # Set final state
            self.state.workflow_step = WorkflowStep.EXCEPTION_INVALID_PROMPT
            self.state.current_agent = "Interface"
            self.state.final_output = self.state.validation_message or "Invalid prompt. Please clarify."

            # Send validation error to GUI if available
            # HostFlow NO LONGER sends messages - GameManager handles this
            # Return None to terminate flow without triggering more listeners
            print(f"[DEBUG] Returning None to terminate HostFlow")
            return None

    @listen("check_difficulty")
    async def evaluate_difficulty(self):
        """Step 4: Judge evaluates difficulty using JudgeFlow"""
        self.state.workflow_step = WorkflowStep.STEP_4_EVALUATE_DIFFICULTY
        self.state.current_agent = "Judge"

        # Create and run JudgeFlow (difficulty assessment phase) - async call
        judge_flow = JudgeFlow()

        # Create and inject GameStateSearchTool into all agent tool lists
        from dnd_mas_host.tools.mongodb_vector_tools import GameStateSearchTool
        #game_state_tool = GameStateSearchTool(self.state)
        #for agent_name in judge_flow.tools:
        #    judge_flow.tools[agent_name].append(game_state_tool)

        await judge_flow.kickoff_async(inputs={
            "campaign": self.state.campaign,
            "player": self.state.main_character.name if self.state.main_character else "",
            "action": self.state.action_extracted,
            "roll": 0,  # Indicates difficulty assessment phase
            "current_venue_obj": self.state.current_venue_obj.model_dump() if self.state.current_venue_obj else None,
            "player_character": self.state.main_character.model_dump() if self.state.main_character else None,
            "active_npcs": [npc.model_dump() for npc in self.state.active_npcs_detailed]
        })

        # Extract results from flow state
        self.state.Action_difficulty = {
            "difficulty": judge_flow.state.difficulty,
            "reasoning": judge_flow.state.difficulty_reasoning
        }
        self.state.skip_difficulty_check = judge_flow.state.skip_difficulty_check

        return self.state

    @router(evaluate_difficulty)
    def route_difficulty(self):
        """Route based on difficulty check requirement"""
        if self.state.skip_difficulty_check:
            return "skip_to_consequences"
        else:
            return "do_perform_check"

    @listen("do_perform_check")
    def perform_check(self):
        """Step 5: Interface performs d20 roll (via GUI if available)"""
        self.state.workflow_step = WorkflowStep.STEP_5_PERFORM_CHECK
        self.state.current_agent = "Interface"

        if self.gui_queues:
            # GUI mode: Send REQUEST_DIFFICULTY_CHECK, then block waiting for ROLL_D20
            from dnd_mas_host.interface.message_types import MessageType, create_message

            print("[DEBUG] perform_check - Sending REQUEST_DIFFICULTY_CHECK to GUI")
            self.gui_queues["from_flow"].put(create_message(
                MessageType.REQUEST_DIFFICULTY_CHECK,
                {
                    "action": self.state.action_extracted.get("action", "Unknown action") if self.state.action_extracted else "Unknown action",
                    "dc": self.state.Action_difficulty.get("difficulty", 10),
                    "skip_check": self.state.skip_difficulty_check,
                    "state": self.state
                }
            ))

            # Block until user responds with roll
            while True:
                try:
                    msg = self.gui_queues["to_flow"].get(timeout=1.0)
                    msg_type = msg.get("type")

                    if msg_type == MessageType.ROLL_D20:
                        self.state.difficulty_check = msg["data"]["roll"]
                        print(f"[DEBUG] perform_check - Received roll: {self.state.difficulty_check}")
                        break
                    elif msg_type == MessageType.CANCEL_ACTION:
                        raise UserCancelledActionException("User cancelled action")
                    elif msg_type == MessageType.SHUTDOWN:
                        raise FlowShutdownException("Flow shutdown requested")
                except queue.Empty:
                    continue
        else:
            # CLI mode: Auto-roll (preserve existing behavior)
            self.state.difficulty_check = randint(1, 20)

        return self.state

    @listen(perform_check)
    @listen("skip_to_consequences")
    async def evaluate_consequences(self):
        """Step 6: Judge evaluates consequences using JudgeFlow"""
        self.state.workflow_step = WorkflowStep.STEP_6_EVALUATE_CONSEQUENCES
        self.state.current_agent = "Judge"

        # Create and run JudgeFlow (consequence evaluation phase) - async call
        judge_flow = JudgeFlow()

        # Create and inject GameStateSearchTool into all agent tool lists
        from dnd_mas_host.tools.mongodb_vector_tools import GameStateSearchTool
        #game_state_tool = GameStateSearchTool(self.state)
        #for agent_name in judge_flow.tools:
        #    judge_flow.tools[agent_name].append(game_state_tool)

        await judge_flow.kickoff_async(inputs={
            "campaign": self.state.campaign,
            "player": self.state.main_character.name if self.state.main_character else "",
            "action": self.state.action_extracted,
            "roll": self.state.difficulty_check,
            "current_venue_obj": self.state.current_venue_obj.model_dump() if self.state.current_venue_obj else None,
            "player_character": self.state.main_character.model_dump() if self.state.main_character else None,
            "active_npcs": [npc.model_dump() for npc in self.state.active_npcs_detailed]
        })

        # Extract results from flow state
        self.state.effect = judge_flow.state.effect
        self.state.workflow_step = WorkflowStep.STEP_6_1_EVALUATE_CONSEQUENCES_COMPLETE
        
        return self.state

    @listen(evaluate_consequences)
    def pre_process_npc_reactions(self):
        
        reactions = self.state.reactions_list
        
        
        char_list = []
        
        char_list.extend(self.state.active_npcs)
        char_list.extend(self.state.companions)
        
        char_list = sorted(char_list, key=lambda x: x.dexterity, reverse=True)
        
        for char in char_list:
            reactions[char] = ''          
        
        
        
        while self.state.workflow_step != WorkflowStep.STEP_6_1_EVALUATE_CONSEQUENCES_COMPLETE:
            time.sleep(0.1)
        return self.state
        
    @listen(pre_process_npc_reactions)
    async def process_reactions_sequentially(self):
        """Steps 7-9: Process reactions one-by-one, ordered by dexterity (high to low)"""
        self.state.workflow_step = WorkflowStep.STEP_7_EVALUATE_NPC_REACTIONS
        self.state.current_agent = "NPC/PC Reactions"

        # Get sorted character list (NPCs + Companions, ordered by DEX high→low)
        sorted_characters = sorted(
            self.state.companions + self.state.active_npcs,
            key=lambda x: x.dexterity if x.dexterity else 10,
            reverse=True  # High DEX first
        )

        if not sorted_characters:
            # No characters to react
            self.state.reactions_list = {}
            return self.state

        print(f"[DEBUG] Processing reactions for {len(sorted_characters)} characters")

        # Process each character sequentially
        all_reactions = {}

        for character in sorted_characters:
            print(f"[DEBUG] Processing reaction for: {character.name} (DEX: {character.dexterity})")

            # Step 7.1: Check if character has reaction (NPC Crew Task 1)
            npc_crew = NpcCrew().crew()

            try:
                reaction_check_result = await npc_crew.kickoff_async(
                    inputs={
                        "campaign": self.state.campaign,
                        "player": self.state.main_character.name if self.state.main_character else "",
                        "NPC_role": character.name,
                        "NPC_goal": character.intentions[0] if character.intentions and len(character.intentions) > 0 else "Survive",
                        "NPC_background": character.description or character.personality or "",
                        "action": self.state.action_extracted,
                        "effect": self.state.effect,
                        "venue": self.state.current_venue,
                        "previous_reactions": all_reactions  # Context of earlier reactions
                    }
                )

                # Parse Task 1 output (ReactionCheckOutput)
                has_reaction = reaction_check_result.pydantic.has_reaction
                print(f"[DEBUG] {character.name} has_reaction: {has_reaction}")

                if not has_reaction:
                    print(f"[DEBUG] {character.name} has no reaction, skipping")
                    all_reactions[character.name] = {
                        "has_reaction": False,
                        "reasoning": reaction_check_result.pydantic.reasoning
                    }
                    continue

                # Step 7.2: Extract structured reaction (NPC Crew Task 2)
                # Note: NPC Crew already ran both tasks sequentially, so result contains both outputs
                reaction_action = reaction_check_result.tasks_output[1].pydantic  # Second task output

                print(f"[DEBUG] {character.name} reacts: {reaction_action.action_type} → {reaction_action.target}")

                # Step 8: Auto-roll difficulty check
                self.state.workflow_step = WorkflowStep.STEP_8_NPC_DIFFICULTY_CHECK
                auto_roll = randint(1, 20)
                print(f"[DEBUG] {character.name} auto-rolled: {auto_roll}")

                # Step 9: Judge evaluates reaction consequences
                self.state.workflow_step = WorkflowStep.STEP_9_NPC_CONSEQUENCES
                judge_flow = JudgeFlow()

                # Inject GameStateSearchTool
                from dnd_mas_host.tools.mongodb_vector_tools import GameStateSearchTool
                game_state_tool = GameStateSearchTool(self.state)
                for agent_name in judge_flow.tools:
                    judge_flow.tools[agent_name].append(game_state_tool)

                await judge_flow.kickoff_async(inputs={
                    "campaign": self.state.campaign,
                    "player": character.name,  # The reacting character
                    "action": {
                        "action_type": reaction_action.action_type,
                        "target": reaction_action.target,
                        "method": reaction_action.method,
                        "intent": reaction_action.intent
                    },
                    "roll": auto_roll,  # Indicates consequence evaluation phase
                    "current_venue_obj": self.state.current_venue_obj.model_dump() if self.state.current_venue_obj else None,
                    "player_character": self.state.main_character.model_dump() if self.state.main_character else None,
                    "active_npcs": [npc.model_dump() for npc in self.state.active_npcs_detailed]
                })

                # Extract consequence from JudgeFlow
                reaction_consequence = judge_flow.state.consequence if hasattr(judge_flow.state, 'consequence') else "No consequence determined"

                # Store complete reaction data
                all_reactions[character.name] = {
                    "has_reaction": True,
                    "action": {
                        "action_type": reaction_action.action_type,
                        "target": reaction_action.target,
                        "method": reaction_action.method,
                        "intent": reaction_action.intent
                    },
                    "roll": auto_roll,
                    "consequence": reaction_consequence
                }

                print(f"[DEBUG] {character.name} consequence: {reaction_consequence}")

            except Exception as e:
                print(f"[ERROR] Failed to process reaction for {character.name}: {e}")
                import traceback
                traceback.print_exc()
                all_reactions[character.name] = {
                    "has_reaction": False,
                    "reasoning": f"Error processing reaction: {str(e)}"
                }

        # Store all reactions in HostState
        self.state.reactions_list = all_reactions
        print(f"[DEBUG] Completed reactions for {len(all_reactions)} characters")

        return self.state

    @listen(process_reactions_sequentially)
    async def generate_narrative(self):
        """Step 10: Narrator generates per-reaction narratives"""
        self.state.workflow_step = WorkflowStep.STEP_10_GENERATE_NARRATIVE
        self.state.current_agent = "Narrator"

        all_narratives = []

        # 1. Generate narrative for player's main action
        print("[DEBUG] Generating narrative for player action")
        narrator_flow = NarratorFlow()

        # Inject GameStateSearchTool
        from dnd_mas_host.tools.mongodb_vector_tools import GameStateSearchTool
        game_state_tool = GameStateSearchTool(self.state)
        for agent_name in narrator_flow.tools:
            narrator_flow.tools[agent_name].append(game_state_tool)

        await narrator_flow.kickoff_async(inputs={
            "campaign": self.state.campaign,
            "player": self.state.main_character.name if self.state.main_character else "",
            "action": self.state.action_extracted,
            "effect": self.state.effect,
            "reactions": {},  # No reactions yet for player action narrative
            "current_venue": self.state.current_venue,
            "current_venue_obj": self.state.current_venue_obj.model_dump() if self.state.current_venue_obj else None,
            "current_stage_obj": self.state.current_stage_obj.model_dump() if self.state.current_stage_obj else None,
            "active_npcs": [npc.model_dump() for npc in self.state.active_npcs_detailed],
            "player_character": self.state.main_character.model_dump() if self.state.main_character else None
        })

        player_narrative = narrator_flow.state.narrative
        all_narratives.append(f"**{self.state.main_character.name}'s Action:**\n{player_narrative}")
        print(f"[DEBUG] Player narrative generated: {len(player_narrative)} chars")

        # Update game state from player action
        state_updates = narrator_flow.state.state_updates
        if self.state.main_character and "character_hp" in state_updates:
            self.state.main_character.update_hp(state_updates["character_hp"])
        self.state.current_venue = state_updates.get("current_venue", self.state.current_venue)

        # 2. Generate narrative for all reactions in a single batch call
        if self.state.reactions_list:
            print(f"[DEBUG] Generating narratives for {len(self.state.reactions_list)} NPC reactions in batch")

            # Prepare NPC reaction data for batch processing
            npc_reaction_list = []
            for char_name, reaction_data in self.state.reactions_list.items():
                if not reaction_data.get("has_reaction"):
                    continue  # Skip non-reactions

                # Find NPC character object
                npc_char = next((npc for npc in self.state.active_npcs_detailed if npc.name == char_name), None)
                npc_reaction_list.append({
                    "npc_name": char_name,
                    "personality": npc_char.personality if npc_char else "",
                    "description": npc_char.description if npc_char else "",
                    "action": reaction_data.get("action", {}),
                    "roll": reaction_data.get("roll", 0),
                    "consequence": reaction_data.get("consequence", "")
                })

            # Single NarratorFlow call for all NPC narratives
            if npc_reaction_list:
                reaction_narrator_flow = NarratorFlow()
                reaction_narrator_flow.state.campaign = self.state.campaign
                reaction_narrator_flow.state.current_venue_obj = self.state.current_venue_obj.model_dump() if self.state.current_venue_obj else None
                reaction_narrator_flow.state.active_npcs = [npc.model_dump() for npc in self.state.active_npcs_detailed]
                reaction_narrator_flow.state.npc_reactions = npc_reaction_list

                # Call the batch NPC narrative generation method
                reaction_narrator_flow.generate_npc_narratives_batch()

                npc_narratives = reaction_narrator_flow.state.npc_narratives
                if npc_narratives:
                    all_narratives.append(f"\n**NPC Reactions:**\n{npc_narratives}")
                    print(f"[DEBUG] Batch NPC narratives generated: {len(npc_narratives)} chars")

        # 3. Combine all narratives
        self.state.final_output = "\n\n".join(all_narratives)
        print(f"[DEBUG] Total narrative length: {len(self.state.final_output)} chars")

        return self.state

    @listen(generate_narrative)
    async def display_output(self):
        """Step 11: Interface displays"""
        self.state.workflow_step = WorkflowStep.STEP_11_DISPLAY_OUTPUT
        self.state.current_agent = "Interface"
        # Display self.state.final_output (handled by interface)
        print(f"\n=== NARRATIVE OUTPUT ===\n{self.state.final_output}\n")

        # Mark flow as complete to stop looping (for debugging)
        self.state.flow_complete = True

        return self.state


def kickoff():
    """
    Main entry point for the D&D MAS flow.

    Example usage:
        flow_instance = HostFlow()
        flow_instance.state.prompt_text = "I want to investigate the slime in the town square"
        flow_instance.state.current_venue = "Town Square"
        flow_instance.kickoff()
    """
    dnd_flow = HostFlow()

    # Example initialization (replace with actual interface integration)
    dnd_flow.state.prompt_text = "I want to explore the town square"
    dnd_flow.state.current_venue = "Town Square"

    result = dnd_flow.kickoff()
    return result


def plot():
    """
    Generate a visualization of the D&D MAS flow execution graph.

    Run with: crewai plot
    """
    dnd_flow = HostFlow()
    dnd_flow.plot()


def run_with_trigger():
    """
    Run the flow with trigger payload for testing/integration.

    Usage:
        python -m dnd_mas_host.main run_with_trigger '{"prompt": "I attack the slime", "venue": "Town Square"}'
    """
    import json
    import sys

    # Get trigger payload from command line argument
    if len(sys.argv) < 2:
        raise Exception("No trigger payload provided. Please provide JSON payload as argument.")

    try:
        trigger_payload = json.loads(sys.argv[1])
    except json.JSONDecodeError:
        raise Exception("Invalid JSON payload provided as argument")

    # Create flow and initialize state with trigger payload
    dnd_flow = HostFlow()

    # Set state from trigger payload
    if "prompt" in trigger_payload:
        dnd_flow.state.prompt_text = trigger_payload["prompt"]
    if "venue" in trigger_payload:
        dnd_flow.state.current_venue = trigger_payload["venue"]

    try:
        result = dnd_flow.kickoff()
        return result
    except Exception as e:
        raise Exception(f"An error occurred while running the flow with trigger: {e}")

