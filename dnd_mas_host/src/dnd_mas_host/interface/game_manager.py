"""
GameManager - Main game lifecycle orchestrator for D&D MAS.

This module manages the entire game from initialization to completion,
including MongoDB integration, state persistence, and HostFlow execution.
"""

import queue
import threading
import traceback
from typing import Optional, Dict, Any
from datetime import datetime

from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

from ..main import HostFlow, UserCancelledActionException, FlowShutdownException
from ..tools.mongodb_vector_tools import MongoDBVectorSearchConfig
from .message_types import MessageType, create_message
from .game_state import GameState, ConversationTurn
from .character import Character


class GameManager:
    """
    Manages the entire D&D game lifecycle.

    Responsibilities:
    - Initialize game from MongoDB (campaign, PCs, starting location)
    - Maintain persistent GameState across prompts
    - Create and reuse single HostFlow instance
    - Sync GameState ↔ HostState before/after each prompt
    - Track conversation history
    - Check win/loss conditions
    - Save game state to MongoDB periodically

    Architecture:
    - Runs in background thread
    - Communicates with GUI via thread-safe queues
    - Maintains persistent HostFlow instance (reused for all prompts)
    - GameState persists across all prompts, HostState resets per prompt
    """

    def __init__(
        self,
        to_flow_queue: queue.Queue,
        from_flow_queue: queue.Queue,
        shutdown_event: threading.Event
    ):
        """
        Initialize GameManager with communication channels.

        Args:
            to_flow_queue: Queue receiving messages from GUI (START_FLOW, ROLL_D20, CANCEL_ACTION)
            from_flow_queue: Queue sending messages to GUI (DISPLAY_NARRATIVE, FLOW_ERROR, etc.)
            shutdown_event: Threading event for clean shutdown signaling
        """
        self.to_flow_queue = to_flow_queue
        self.from_flow_queue = from_flow_queue
        self.shutdown_event = shutdown_event

        # Persistent game state
        self.game_state: Optional[GameState] = None

        # Persistent HostFlow instance (created once, reused)
        self.host_flow: Optional[HostFlow] = None

        # MongoDB connection
        self.mongo_client: Optional[MongoClient] = None
        self.campaign_db = None

    def initialize_game(self) -> bool:
        """
        Load campaign data from MongoDB and initialize GameState.

        Steps:
        1. Connect to MongoDB
        2. Load campaign from 'stories' collection (includes startStage, startVenue)
        3. Load PC (Aldric) from 'PCs' collection (character_type='main_character')
        4. Extract starting stage and venue names from campaign document
        5. Populate GameState with loaded data
        6. Create HostFlow instance (persistent)

        Returns:
            True if successful, False on error
        """
        try:
            print("[GameManager] Initializing game...")

            # Step 1: Connect to MongoDB
            print("[GameManager] Connecting to MongoDB...")
            self.mongo_client = MongoClient(
                MongoDBVectorSearchConfig.MONGO_URI,
                serverSelectionTimeoutMS=5000
            )
            self.mongo_client.admin.command('ping')  # Force connection check
            self.campaign_db = self.mongo_client["campaign"]
            print("[GameManager] MongoDB connected successfully")

            # Step 2: Load campaign from 'stories' collection
            print("[GameManager] Loading campaign data...")
            campaign_doc = self.campaign_db["stories"].find_one({"name": "Humantown: Rescue from the Town of Slimes"})
            if not campaign_doc:
                print("[GameManager] ERROR: Campaign 'Humantown' not found in database")
                return False

            # Step 3: Load main character (Aldric) from 'PCs' collection
            print("[GameManager] Loading main character (Aldric)...")
            pc_doc = self.campaign_db["PCs"].find_one({"character_type": "main_character"})
            if not pc_doc:
                print("[GameManager] ERROR: Main character not found in PCs collection")
                return False

            # Create Character instance from PC document
            main_character = Character.from_pc_document(pc_doc)
            print(f"[GameManager]   - Loaded: {main_character.name} (Level {main_character.level} {main_character.character_class})")

            # Step 4: Load companion characters (Jaylen)
            print("[GameManager] Loading companion characters...")
            companions = []
            companion_docs = self.campaign_db["PCs"].find({"character_type": "companion"})
            for companion_doc in companion_docs:
                companion = Character.from_pc_document(companion_doc)
                companions.append(companion)
                print(f"[GameManager]   - Loaded companion: {companion.name}")

            # Step 5: Get starting stage and venue names directly from campaign document
            print("[GameManager] Reading starting stage and venue...")
            starting_stage_name = campaign_doc.get("startStage", "Arrival and Investigation")
            starting_venue_name = campaign_doc.get("startVenue", "Welcome Sign")
            print(f"[GameManager]   - Starting stage: {starting_stage_name}")
            print(f"[GameManager]   - Starting venue: {starting_venue_name}")

            # Step 6: Populate GameState
            print("[GameManager] Populating GameState...")
            self.game_state = GameState(
                campaign="Humantown",
                main_character=main_character,
                companions=companions,
                current_stage=starting_stage_name,
                current_venue=starting_venue_name,
                start_narrative=campaign_doc.get("startNarrative", "Your adventure begins..."),
                main_objective=campaign_doc.get("objective", "Rescue Jaylen from Humantown"),
                save_id=f"aldric_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            )

            print(f"[GameManager] GameState initialized:")
            print(f"[GameManager]   - Player: {main_character.name} (Level {main_character.level} {main_character.character_class})")
            print(f"[GameManager]   - HP: {main_character.hp}/{main_character.max_hp}, AC: {main_character.ac}")
            print(f"[GameManager]   - Companions: {len(companions)}")
            print(f"[GameManager]   - Location: {self.game_state.current_venue} ({self.game_state.current_stage})")

            # Step 7: Create HostFlow instance (persistent, reused for all prompts)
            print("[GameManager] Creating HostFlow instance...")
            self.host_flow = HostFlow(gui_queues={
                "to_flow": self.to_flow_queue,
                "from_flow": self.from_flow_queue
            })
            print("[GameManager] HostFlow created successfully")

            print("[GameManager] Game initialization complete!")
            return True

        except ConnectionFailure as e:
            print(f"[GameManager] MongoDB connection failed: {e}")
            return False
        except Exception as e:
            print(f"[GameManager] Initialization error: {e}")
            traceback.print_exc()
            return False

    def sync_game_to_host_state(self):
        """
        Sync GameState → HostState before kickoff().

        Copies:
        - campaign, main_character, companions, current_stage, current_venue
        - active_npcs (query MongoDB venues collection for NPCs in current venue)
        - previous_prompt, previous_narrative (from last conversation turn)
        """
        if not self.host_flow or not self.game_state:
            return

        print(f"[GameManager] Syncing GameState → HostState")

        # Sync basic game state using Character objects
        self.host_flow.state.campaign = self.game_state.campaign
        self.host_flow.state.main_character = self.game_state.main_character
        self.host_flow.state.companions = self.game_state.companions
        self.host_flow.state.current_stage = self.game_state.current_stage
        self.host_flow.state.current_venue = self.game_state.current_venue

        # Sync conversation context (previous turn)
        if self.game_state.conversation_history:
            last_turn = self.game_state.conversation_history[-1]
            self.host_flow.state.previous_prompt = last_turn.prompt
            self.host_flow.state.previous_narrative = last_turn.narrative

        # Query active NPCs in current venue from MongoDB and convert to Character objects
        try:
            venue_doc = self.campaign_db["venues"].find_one({"name": self.game_state.current_venue})
            if venue_doc and "NPCs" in venue_doc:
                npc_ids = venue_doc["NPCs"]
                active_npcs = []
                for npc_id in npc_ids:
                    npc_doc = self.campaign_db["NPCs"].find_one({"_id": npc_id})
                    if npc_doc:
                        # Convert NPC document to Character object
                        npc_character = Character.from_npc_document(npc_doc)
                        active_npcs.append(npc_character)
                self.host_flow.state.active_npcs = active_npcs
                print(f"[GameManager]   - Loaded {len(active_npcs)} NPCs for venue '{self.game_state.current_venue}'")
        except Exception as e:
            print(f"[GameManager] WARNING: Failed to load NPCs: {e}")
            self.host_flow.state.active_npcs = []

    def sync_host_to_game_state(self):
        """
        Sync HostState → GameState after kickoff().

        Updates:
        - main_character (from HostState, which may have been modified by consequences)
        - companions (synced back from HostState)
        - current_venue (if changed by narrative)
        - current_stage (if advanced)
        - Add ConversationTurn to conversation_history
        - Increment total_turns
        """
        if not self.host_flow or not self.game_state:
            return

        print(f"[GameManager] Syncing HostState → GameState")

        # Store HP before update for conversation history
        hp_before = self.game_state.main_character.hp if self.game_state.main_character else 0

        # Sync character objects back from HostState (may have been modified)
        self.game_state.main_character = self.host_flow.state.main_character
        self.game_state.companions = self.host_flow.state.companions

        # Update location
        self.game_state.current_venue = self.host_flow.state.current_venue
        self.game_state.current_stage = self.host_flow.state.current_stage

        # Add conversation turn to history
        turn = ConversationTurn(
            prompt=self.host_flow.state.prompt_text,
            narrative=self.host_flow.state.final_output,
            hp_before=hp_before,
            hp_after=self.game_state.main_character.hp if self.game_state.main_character else 0,
            venue=self.game_state.current_venue,
            stage=self.game_state.current_stage
        )
        self.game_state.conversation_history.append(turn)
        self.game_state.total_turns += 1

        print(f"[GameManager]   - Turn {self.game_state.total_turns} recorded")
        print(f"[GameManager]   - HP: {hp_before} → {self.game_state.main_character.hp if self.game_state.main_character else 0}")

    def check_win_loss_conditions(self) -> Optional[str]:
        """
        Check if game has ended.

        Win conditions:
        - Jaylen rescued (HP > 0, location changed from Mill Laboratory)
        - Party escapes Humantown successfully

        Loss conditions:
        - Aldric HP <= 0
        - Jaylen HP <= 0 (quest failure)

        Returns:
            None if game continues, "victory" or "defeat:<reason>" if ended
        """
        if not self.game_state:
            return None

        # Check loss condition: Main character (Aldric) HP <= 0
        if self.game_state.main_character and not self.game_state.main_character.is_alive():
            self.game_state.game_over = True
            self.game_state.victory = False
            self.game_state.defeat_reason = f"{self.game_state.main_character.name} has fallen"
            return f"defeat:{self.game_state.defeat_reason}"

        # Check Jaylen status (companion or from MongoDB)
        jaylen = None

        # First check if Jaylen is in companions list
        for companion in self.game_state.companions:
            if "jaylen" in companion.name.lower():
                jaylen = companion
                break

        # If not in companions, check MongoDB
        if not jaylen:
            try:
                jaylen_doc = self.campaign_db["PCs"].find_one({"index": "jaylen-shadowstep"})
                if jaylen_doc:
                    jaylen = Character.from_pc_document(jaylen_doc)
            except Exception as e:
                print(f"[GameManager] WARNING: Failed to check Jaylen status: {e}")

        # Check Jaylen win/loss conditions
        if jaylen:
            # Loss: Jaylen HP <= 0
            if not jaylen.is_alive():
                self.game_state.game_over = True
                self.game_state.victory = False
                self.game_state.defeat_reason = "Jaylen Shadowstep has perished"
                return f"defeat:{self.game_state.defeat_reason}"

            # Win: Jaylen rescued (location changed from Mill Laboratory)
            jaylen_location = jaylen.location or "Mill Laboratory (M3)"
            if "Mill Laboratory" not in jaylen_location and jaylen.is_alive():
                # Additional check: Party must escape Humantown
                if self.game_state.current_stage == "Escape" or "escaped" in self.game_state.current_venue.lower():
                    self.game_state.game_over = True
                    self.game_state.victory = True
                    return "victory"

        return None  # Game continues

    def save_game_to_mongodb(self):
        """
        Persist GameState to MongoDB 'game_saves' collection.

        Saves:
        - Full GameState as JSON document
        - Update last_saved timestamp
        """
        if not self.game_state or not self.campaign_db:
            return

        try:
            self.game_state.last_saved = datetime.now()
            save_doc = self.game_state.to_mongodb_dict()

            # Upsert to game_saves collection
            self.campaign_db["game_saves"].update_one(
                {"save_id": self.game_state.save_id},
                {"$set": save_doc},
                upsert=True
            )
            print(f"[GameManager] Game saved to MongoDB (save_id: {self.game_state.save_id})")
        except Exception as e:
            print(f"[GameManager] WARNING: Failed to save game: {e}")




    def run(self):
        """
        Main game loop (runs in background thread).

        Workflow:
        1. Initialize game from MongoDB
        2. Send FLOW_READY to GUI
        3. While not shutdown:
            a. Wait for START_FLOW message
            b. Sync GameState → HostState
            c. Reset HostState workflow fields
            d. Execute host_flow.kickoff() (reuse instance)
            e. Sync HostState → GameState
            f. Check win/loss conditions
            g. Save to MongoDB (every 5 turns or on game end)
            h. Send DISPLAY_NARRATIVE to GUI
        """
        print("[GameManager] Starting game manager thread")

        # Step 1: Initialize game from MongoDB
        if not self.initialize_game():
            self.from_flow_queue.put(create_message(
                MessageType.FLOW_ERROR,
                {"error": "Failed to initialize game from MongoDB",
                 "state": self.host_flow.state
                 }
            ))
            return

        # Step 2: Send FLOW_READY + initial narrative to GUI
        self.from_flow_queue.put(create_message(
            MessageType.FLOW_READY,
            {"message": "Game initialized successfully",
                 "state": self.host_flow.state}
        ))

        # Send start narrative as first message
        self.from_flow_queue.put(create_message(
            MessageType.DISPLAY_NARRATIVE,
            {
                "narrative": self.game_state.start_narrative,
                 "state": self.host_flow.state
            }
        ))

        # Step 3: Main game loop
        while not self.shutdown_event.is_set():
            try:
                # Wait for messages from GUI
                try:
                    msg = self.to_flow_queue.get(timeout=1.0)
                except queue.Empty:
                    continue

                msg_type = msg.get("type")

                # Handle shutdown request
                if msg_type == MessageType.SHUTDOWN:
                    print("[GameManager] Received shutdown signal")
                    break

                # Handle flow start request
                if msg_type == MessageType.START_FLOW:
                    prompt = msg["data"].get("prompt", "")
                    print(f"[GameManager] Processing prompt: {prompt[:50]}...")

                    try:
                        # Step 3a: Sync GameState → HostState
                        self.sync_game_to_host_state()

                        # Step 3b: Reset HostState workflow fields
                        self.host_flow.reset_state()

                        # Step 3c: Load enriched context (venue/stage objects from MongoDB)
                        print("[GameManager] Loading enriched context...")
                        self.host_flow.load_enriched_context()

                        # Set current prompt
                        self.host_flow.state.prompt_text = prompt

                        # Step 3d: Execute host_flow.kickoff() (reuse instance)
                        print("[GameManager] Executing HostFlow.kickoff()...")
                        result = self.host_flow.kickoff()
                        print("[GameManager] HostFlow.kickoff() completed")

                        # Step 3d: Check workflow outcome and send appropriate message

                        # Case 1: Validation failed - send VALIDATION_ERROR
                        if not self.host_flow.state.prompt_valid:
                            print("[GameManager] Validation failed, sending VALIDATION_ERROR")
                            self.from_flow_queue.put(create_message(
                                MessageType.VALIDATION_ERROR,
                                {
                                    "message": self.host_flow.state.validation_message or "Invalid prompt. Please clarify.",
                                    "state": self.host_flow.state
                                }
                            ))
                            continue  # Skip rest of processing, wait for new prompt

                        # Case 2: Normal completion - sync state and send DISPLAY_NARRATIVE
                        # (HostFlow handles REQUEST_DIFFICULTY_CHECK internally)
                        # Step 3e: Sync HostState → GameState
                        self.sync_host_to_game_state()

                        # Step 3f: Check win/loss conditions
                        game_status = self.check_win_loss_conditions()
                        if game_status:
                            print(f"[GameManager] Game ended: {game_status}")

                        # Step 3g: Save to MongoDB (every 5 turns or on game end)
                        if self.game_state.total_turns % 5 == 0 or self.game_state.game_over:
                            self.save_game_to_mongodb()

                        # Step 3h: Send DISPLAY_NARRATIVE to GUI
                        self.from_flow_queue.put(create_message(
                            MessageType.DISPLAY_NARRATIVE,
                            {
                                "narrative": self.host_flow.state.final_output,
                                "state": self.host_flow.state,
                                "game_status": game_status  # victory/defeat/None
                            }
                        ))

                        print("[GameManager] Turn completed successfully")

                    except UserCancelledActionException:
                        print("[GameManager] User cancelled action")
                        continue

                    except FlowShutdownException:
                        print("[GameManager] Flow shutdown requested")
                        break

                    except Exception as e:
                        error_msg = str(e)
                        error_trace = traceback.format_exc()
                        print(f"[GameManager] Flow error: {error_msg}")
                        print(error_trace)

                        self.from_flow_queue.put(create_message(
                            MessageType.FLOW_ERROR,
                            {
                                "error": error_msg,
                                "traceback": error_trace,
                                "state": self.host_flow.state
                            }
                        ))

            except Exception as e:
                print(f"[GameManager] Unexpected thread error: {e}")
                traceback.print_exc()

                self.from_flow_queue.put(create_message(
                    MessageType.FLOW_ERROR,
                    {
                        "error": f"Thread error: {str(e)}",
                        "traceback": traceback.format_exc(),
                        "state": self.host_flow.state
                    }
                ))

        # Cleanup
        if self.mongo_client:
            self.mongo_client.close()
            print("[GameManager] MongoDB connection closed")

        print("[GameManager] Game manager thread exiting")
