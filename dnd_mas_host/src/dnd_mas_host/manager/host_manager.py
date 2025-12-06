"""
HostManager - Backbone of the D&D MAS message-passing architecture.

This module implements the HostManager which owns the unified message queue,
routes all messages to appropriate agents, kicks off agent execution,
and handles NPC crew management.
"""

import random
import traceback
from typing import Dict, Optional, Any, TYPE_CHECKING
from queue import Queue

from pymongo import MongoClient

from dnd_mas_host.state.blackboard_manager import BlackboardManager
from dnd_mas_host.tools.mongodb_vector_tools import MongoDBVectorSearchConfig
from dnd_mas_host.state.host_state import (
    HostState,
    GameContext,
    Action,
    ActionType,
    Consequence,
    ConsequenceType,
    WorkflowStep,
)
from dnd_mas_host.interface.message_types import Message, MessageType, create_message
from dnd_mas_host.interface.models import Campaign
from dnd_mas_host.interface.character import Character
from dnd_mas_host.config import MAX_RETRY_LIMIT

if TYPE_CHECKING:
    from dnd_mas_host.crews.npc_crew.npc_crew import NpcCrew
    from dnd_mas_host.crews.narrator_crew.narrator_crew import NarratorFlow
    from dnd_mas_host.crews.judge_crew.judge_crew import JudgeFlow


class HostManager:
    """
    BACKBONE OF THE SYSTEM: Owns message queue, routes messages, kicks off agents.

    Responsibilities:
    1. Owns and manages the Unified Message Queue
    2. Routes ALL messages to appropriate agents
    3. Kicks off agent execution (NarratorFlow, JudgeFlow, InterfaceAgent)
    4. Manages NPC crews (create/reuse/delete, DEX order processing)
    5. Owns BlackboardManager instance

    Entry Point: Called by InterfaceAgent after GUI initialization.
    """

    def __init__(
        self,
        campaign_name: str,
        mongo_uri: str = None,
        interface_callback=None
    ):
        """
        Initialize HostManager.

        Args:
            campaign_name: Name of campaign to load (e.g., "Humantown: Rescue from the Town of Slimes")
            mongo_uri: MongoDB connection URI (defaults to MongoDBVectorSearchConfig.MONGO_URI)
            interface_callback: Callback function to send messages to InterfaceAgent
        """
        # Use consistent MongoDB URI from config
        if mongo_uri is None:
            mongo_uri = MongoDBVectorSearchConfig.MONGO_URI
        print("[HostManager] Initializing...")

        # Message queue
        self.message_queue: Queue[Message] = Queue()

        # Interface callback for GUI communication
        self.interface_callback = interface_callback

        # Load campaign and initialize context
        self._initialize_game_context(campaign_name, mongo_uri)

        # Initialize blackboard with game context
        self.blackboard = BlackboardManager(self._game_context)

        # Lazy-load crews (created on first use)
        self._narrator_flow = None
        self._judge_flow = None

        # NPC crews dict (managed dynamically: REUSE/CREATE/DELETE)
        self.npc_crews: Dict[str, Any] = {}

        # Running flag
        self._running = False

        print("[HostManager] Initialization complete")

    def _initialize_game_context(self, campaign_name: str, mongo_uri: str):
        """
        Initialize GameContext by loading campaign and character data.

        Args:
            campaign_name: Name of campaign to load
            mongo_uri: MongoDB connection URI
        """
        print(f"[HostManager] Loading campaign: {campaign_name}")

        # Load campaign with all stages, venues, NPCs
        campaign = Campaign.load_from_db(campaign_name, mongo_uri)

        # Load main character and companions from MongoDB
        print("[HostManager] Loading characters...")
        print(f"[HostManager] Using MongoDB URI: {mongo_uri}")
        client = MongoClient(mongo_uri)
        db = client["campaign"]

        try:
            # Load main character
            pc_doc = db["PCs"].find_one({"character_type": "main_character"})
            if not pc_doc:
                raise ValueError("Main character not found in PCs collection")

            main_character = Character.from_pc_document(pc_doc)
            print(f"[HostManager]   - Main character: {main_character.name}")

            # Load companions
            companions = []
            companion_names = []
            companion_docs = db["PCs"].find({"character_type": "party_member"})
            companion_count = db["PCs"].count_documents({"character_type": "party_member"})
            print(f"[HostManager] Found {companion_count} companions in database")

            for companion_doc in companion_docs:
                print(f"[HostManager]   - Loading companion doc: {companion_doc.get('name', 'Unknown')}")
                companion = Character.from_pc_document(companion_doc)
                companions.append(companion)
                companion_names.append(companion.name)
                print(f"[HostManager]   - Companion loaded: {companion.name} (HP: {companion.hp}/{companion.max_hp})")

            # Build all_characters dict
            all_characters = {main_character.name: main_character.to_dict()}
            for companion in companions:
                all_characters[companion.name] = companion.to_dict()

            print(f"[HostManager] Built all_characters dict with {len(all_characters)} characters:")
            for char_name in all_characters.keys():
                char_data = all_characters[char_name]
                print(f"[HostManager]   - {char_name}: HP={char_data.get('hp')}/{char_data.get('max_hp')}, Class={char_data.get('character_class')}")

            # Create GameContext
            self._game_context = GameContext(
                campaign_name=campaign.name,
                campaign_objective=campaign.objective,
                campaign_outline=campaign.outline,
                main_character_name=main_character.name,
                companion_names=companion_names,
                current_stage_name=campaign.start_stage,
                current_venue_name=campaign.start_venue,
                all_stages=campaign.stages,
                all_venues=campaign.all_venues,
                all_npcs=campaign.all_npcs,
                all_characters=all_characters
            )

            print(f"[HostManager] GameContext created:")
            print(f"[HostManager]   - Campaign: {self._game_context.campaign_name}")
            print(f"[HostManager]   - Stage: {self._game_context.current_stage_name}")
            print(f"[HostManager]   - Venue: {self._game_context.current_venue_name}")

        finally:
            client.close()

    @property
    def narrator_flow(self):
        """Lazy-load NarratorFlow on first access."""
        if self._narrator_flow is None:
            from dnd_mas_host.crews.narrator_crew.narrator_crew import NarratorFlow
            self._narrator_flow = NarratorFlow()
            self._narrator_flow.host_manager = self
            self._narrator_flow.bb = self.blackboard
            print("[HostManager] NarratorFlow created")
        return self._narrator_flow

    @property
    def judge_flow(self):
        """Lazy-load JudgeFlow on first access."""
        if self._judge_flow is None:
            from dnd_mas_host.crews.judge_crew.judge_crew import JudgeFlow
            self._judge_flow = JudgeFlow()
            self._judge_flow.host_manager = self
            self._judge_flow.bb = self.blackboard
            print("[HostManager] JudgeFlow created")
        return self._judge_flow

    # ========================================================================
    # Message Queue Operations
    # ========================================================================

    def send_message(self, msg: Message):
        """
        Add a message to the queue for processing.

        Args:
            msg: Message to queue
        """
        print(f"[HostManager] Queueing message: {msg.type} → {msg.to}")
        self.message_queue.put(msg)

    def run(self):
        """
        Main loop: process messages from queue.

        This runs until shutdown is requested.
        """
        print("[HostManager] Starting main loop...")
        self._running = True

        while self._running:
            try:
                # Get message with timeout to allow for shutdown checks
                try:
                    msg = self.message_queue.get(timeout=1.0)
                except:
                    continue

                self._route_message(msg)

            except Exception as e:
                print(f"[HostManager] Error in main loop: {e}")
                traceback.print_exc()
                # Send error to interface
                if self.interface_callback:
                    self.interface_callback(create_message(
                        to="Interface",
                        msg_type=MessageType.FLOW_ERROR,
                        data={"error": str(e), "traceback": traceback.format_exc()},
                        from_agent="HostManager"
                    ))

        print("[HostManager] Main loop exited")

    def shutdown(self):
        """Signal the main loop to stop."""
        print("[HostManager] Shutdown requested")
        self._running = False

    def _route_message(self, msg: Message):
        """
        Universal message router.

        Routes messages to appropriate handlers based on recipient.

        Args:
            msg: Message to route
        """
        print(f"[HostManager] Routing: {msg.type} → {msg.to}")

        if msg.to == "Interface":
            self._handle_interface_message(msg)
        elif msg.to == "Narrator":
            self._execute_narrator(msg)
        elif msg.to == "Judge":
            self._execute_judge(msg)
        elif msg.to == "NPC":
            self._process_npc_reactions()
        else:
            print(f"[HostManager] Unknown recipient: {msg.to}")

    # ========================================================================
    # Interface Message Handling
    # ========================================================================

    def _handle_interface_message(self, msg: Message):
        """
        Forward message to InterfaceAgent via callback.

        Args:
            msg: Message for Interface
        """
        if self.interface_callback:
            self.interface_callback(msg)
        else:
            print(f"[HostManager] No interface callback - message dropped: {msg.type}")

    # ========================================================================
    # Narrator Flow Execution
    # ========================================================================

    def _execute_narrator(self, msg: Message):
        """
        Kick off NarratorFlow based on message type.

        Args:
            msg: Message triggering narrator execution
        """
        print(f"[HostManager] Executing Narrator for: {msg.type}")

        inputs = {
            "msg": msg            
        }

        result = self._execute_flow_with_retry(self.narrator_flow, inputs, "Narrator")


    # ========================================================================
    # Judge Flow Execution
    # ========================================================================

    def _execute_judge(self, msg: Message):
        """
        Kick off JudgeFlow based on message type.

        Args:
            msg: Message triggering judge execution
        """
        print(f"[HostManager] Executing Judge for: {msg.type}")

        inputs = {
            "msg": msg
        }

        result = self._execute_flow_with_retry(self.judge_flow, inputs, "Judge")

        # For NPC consequence evaluation, return the result for caller to handle
        if msg.type == MessageType.EVALUATE_NPC_CONSEQUENCE and result:
            return self._parse_effect_to_consequences(
                result.state.effect,
                msg.data.get("action", {}).get("target") if msg.data else None
            )

        return None

    # ========================================================================
    # NPC Processing
    # ========================================================================

    def _process_npc_reactions(self):
        """Process all NPC reactions sequentially (DEX order)."""
        print("[HostManager] Processing NPC reactions...")

        bb = self.blackboard

        # Update active NPCs list and get sorted names
        active_npc_names = bb.update_active_npcs(self.npc_crews)

        reactions_list = {}
        reactions_consequence_list = {}

        for npc_name in active_npc_names:
            print(f"[HostManager] Processing NPC: {npc_name}...")

            # Get or create NPC crew
            if npc_name not in self.npc_crews:
                from dnd_mas_host.crews.npc_crew.npc_crew import NpcCrew
                self.npc_crews[npc_name] = NpcCrew()
                print(f"[HostManager]   - Created new crew for: {npc_name}")

            crew = self.npc_crews[npc_name]

            # Get NPC data
            npc_data = bb.get_npc_data(npc_name)
            if not npc_data:
                npc_data = bb.get_character_data(npc_name)  # Check companions
            if not npc_data:
                print(f"[HostManager]   - No data found for: {npc_name}, skipping")
                continue

            # Read context
            action = bb.read_single("current_turn.action_extracted")
            mc_consequence = bb.read_single("current_turn.mc_consequence")
            venue_data = bb.get_current_venue_data() or {}

            # Build inputs for NPC crew
            inputs = {
                "npc_name": npc_name,
                "npc_profile": npc_data,
                "player_action": action.model_dump() if hasattr(action, 'model_dump') else (action or {}),
                "player_consequence": [c.model_dump() if hasattr(c, 'model_dump') else c for c in (mc_consequence or [])],
                "current_venue": venue_data
            }

            try:
                # Execute NPC crew
                result = self._execute_crew_with_retry(crew, inputs)
                if result is None:
                    continue

                # Extract reaction from crew output
                has_reaction = False
                reaction_action = None

                if result.tasks_output and len(result.tasks_output) >= 2:
                    # First task: if_reaction
                    reaction_check = result.tasks_output[0]
                    if hasattr(reaction_check, 'pydantic') and reaction_check.pydantic:
                        has_reaction = reaction_check.pydantic.has_reaction
                    elif hasattr(reaction_check, 'raw'):
                        has_reaction = "true" in str(reaction_check.raw).lower()

                    # Second task: extract_reaction
                    if has_reaction:
                        reaction_output = result.tasks_output[1]
                        if hasattr(reaction_output, 'pydantic') and reaction_output.pydantic:
                            reaction_data = reaction_output.pydantic.dict()
                        else:
                            reaction_data = {}

                        # Create Action object
                        reaction_action = Action(
                            action_type=ActionType(reaction_data.get("action_type", "other")),
                            actor_name=npc_name,
                            target=reaction_data.get("target"),
                            method=reaction_data.get("method", ""),
                            intent=reaction_data.get("intent", "")
                        )

                if has_reaction and reaction_action:
                    print(f"[HostManager]   - {npc_name} reacts: {reaction_action.action_type}")

                    # Get difficulty for NPC action
                    # (Simplified: use average DC of 10 for NPCs)
                    npc_roll = random.randint(1, 20)
                    print(f"[HostManager]   - {npc_name} rolls d20: {npc_roll}")

                    # Evaluate NPC consequence via message
                    npc_consequences = self._execute_judge(create_message(
                        to="Judge",
                        msg_type=MessageType.EVALUATE_NPC_CONSEQUENCE,
                        data={
                            "npc_name": npc_name,
                            "action": reaction_action.model_dump(),
                            "roll": npc_roll
                        },
                        from_agent="HostManager"
                    ))

                    reactions_list[npc_name] = reaction_action
                    reactions_consequence_list[npc_name] = npc_consequences if npc_consequences else []
                else:
                    print(f"[HostManager]   - {npc_name} has no reaction")

            except Exception as e:
                print(f"[HostManager]   - Error processing {npc_name}: {e}")
                traceback.print_exc()
                continue

        # Write reactions to blackboard
        bb.write({
            "current_turn.reactions_list": reactions_list,
            "current_turn.reactions_consequence_list": reactions_consequence_list
        })

        # Send GENERATE_NARRATIVE to Narrator
        self.send_message(create_message(
            to="Narrator",
            msg_type=MessageType.GENERATE_NARRATIVE,
            from_agent="NPC"
        ))

    # ========================================================================
    # Helper Methods
    # ========================================================================

    def _execute_flow_with_retry(self, flow, inputs: Dict, agent_name: str):
        """
        Execute a Flow with retry logic.

        Args:
            flow: Flow instance to execute
            inputs: Input dictionary for kickoff
            agent_name: Name of agent for logging

        Returns:
            Flow result or None on failure
        """
        for attempt in range(MAX_RETRY_LIMIT + 1):
            try:
                print(f"[HostManager] {agent_name} attempt {attempt + 1}/{MAX_RETRY_LIMIT + 1}")
                return flow.kickoff(inputs=inputs)
            except Exception as e:
                print(f"[HostManager] {agent_name} failed (attempt {attempt + 1}): {e}")
                if attempt >= MAX_RETRY_LIMIT:
                    self._handle_agent_error(agent_name, e)
                    return None
        return None

    def _execute_crew_with_retry(self, crew, inputs: Dict):
        """
        Execute a Crew with retry logic.

        Args:
            crew: Crew instance to execute
            inputs: Input dictionary for kickoff

        Returns:
            Crew result or None on failure
        """
        for attempt in range(MAX_RETRY_LIMIT + 1):
            try:
                print(f"[HostManager] NPC crew attempt {attempt + 1}/{MAX_RETRY_LIMIT + 1}")
                return crew.crew().kickoff(inputs=inputs)
            except Exception as e:
                print(f"[HostManager] NPC crew failed (attempt {attempt + 1}): {e}")
                if attempt >= MAX_RETRY_LIMIT:
                    return None
        return None

    def _handle_agent_error(self, agent_name: str, error: Exception):
        """
        Handle agent execution error.

        Args:
            agent_name: Name of failed agent
            error: Exception that occurred
        """
        error_msg = f"{agent_name} execution failed: {str(error)}"
        print(f"[HostManager] {error_msg}")

        # Log to blackboard
        self.blackboard.write({
            "workflow.current_step": WorkflowStep.ERROR,
            "workflow.error_log": self.blackboard.read_single("workflow.error_log") + [
                {"agent": agent_name, "error": str(error)}
            ]
        })

        # Send error to Interface
        self.send_message(create_message(
            to="Interface",
            msg_type=MessageType.FLOW_ERROR,
            data={"error": error_msg, "agent": agent_name},
            from_agent="HostManager"
        ))

    def _consequences_to_effect_string(self, consequences: list) -> str:
        """Convert list of Consequence objects to effect string."""
        if not consequences:
            return ""

        effects = []
        for c in consequences:
            if hasattr(c, 'description'):
                effects.append(c.description)
            elif isinstance(c, dict):
                effects.append(c.get("description", ""))
            else:
                effects.append(str(c))

        return "; ".join(effects)

    def _parse_effect_to_consequences(self, effect: str, target: Optional[str]) -> list:
        """
        Parse effect string to list of Consequence objects.

        This is a simplified parser - in production you'd want more sophisticated parsing.

        Args:
            effect: Effect description string
            target: Default target name

        Returns:
            List of Consequence objects
        """
        if not effect:
            return []

        # Create a generic consequence from the effect string
        return [Consequence(
            consequence_type=ConsequenceType.ENVIRONMENTAL,  # Generic type
            target_name=target or "unknown",
            description=effect
        )]

    # ========================================================================
    # Public API for InterfaceAgent
    # ========================================================================

    def handle_user_prompt(self, prompt: str):
        """
        Process a user prompt.

        Called by InterfaceAgent when user submits a prompt.

        Args:
            prompt: User's prompt text
        """
        print(f"[HostManager] Handling user prompt: {prompt[:50]}...")

        # Reset turn state
        self.blackboard.reset_turn()

        # Write prompt to blackboard
        self.blackboard.write({
            "current_turn.prompt_text": prompt,
            "workflow.current_step": WorkflowStep.STEP_1_RECEIVE_PROMPT
        })

        # Send to Narrator for validation
        self.send_message(create_message(
            to="Narrator",
            msg_type=MessageType.VALIDATE_PROMPT,
            from_agent="Interface"
        ))

    def handle_roll_result(self, roll: int):
        """
        Process a dice roll result.

        Called by InterfaceAgent after user rolls d20.

        Args:
            roll: The d20 roll result (1-20)
        """
        print(f"[HostManager] Handling roll result: {roll}")

        # Write roll to blackboard
        self.blackboard.write({
            "current_turn.difficulty_check": roll,
            "workflow.current_step": WorkflowStep.STEP_5_PERFORM_CHECK
        })

        # Send to Judge for consequence evaluation
        self.send_message(create_message(
            to="Judge",
            msg_type=MessageType.EVALUATE_CONSEQUENCE,
            from_agent="Interface"
        ))

    def handle_cancel(self):
        """
        Handle user cancellation.

        Called by InterfaceAgent when user cancels action.
        """
        print("[HostManager] User cancelled action")

        # Reset turn state
        self.blackboard.reset_turn()

    def get_start_narrative(self) -> str:
        """Get the campaign's starting narrative."""
        stages = self.blackboard.read_single("game_context.all_stages")
        start_stage = self.blackboard.read_single("game_context.current_stage_name")
        if stages and start_stage in stages:
            return stages[start_stage].get("startNarrative", "Your adventure begins...")
        return "Your adventure begins..."

    def get_game_context_summary(self) -> Dict[str, Any]:
        """Get a summary of current game context for GUI display."""
        bb = self.blackboard
        mc_name = bb.read_single("game_context.main_character_name")
        mc_data = bb.get_character_data(mc_name) or {}

        return {
            "campaign": bb.read_single("game_context.campaign_name"),
            "player": mc_name,
            "player_hp": mc_data.get("current_hit_points", mc_data.get("hit_points", 0)),
            "player_max_hp": mc_data.get("hit_points", 0),
            "current_stage": bb.read_single("game_context.current_stage_name"),
            "current_venue": bb.read_single("game_context.current_venue_name")
        }