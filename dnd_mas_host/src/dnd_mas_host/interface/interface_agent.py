"""
Interface Agent - GUI component for D&D Multi-Agent System.

Architecture:
- Listener: PySimpleGUI event loop (main thread)
- Processor: Conversation history, game state, thread coordination
- No Reasoning LLM (pure interface component)

Threading:
- Main thread: GUI event loop (window.read())
- Background thread: HostFlow execution
- Communication: Queues + thread-safe message passing
"""

from datetime import datetime
import queue
import threading
import sys
from typing import Optional, List, Dict, Any
from random import randint

import PySimpleGUI as sg
from pydantic import BaseModel, Field
from pymongo import MongoClient

from ..tools.mongodb_vector_tools import MongoDBVectorSearchConfig
from .message_types import MessageType, create_message
from .game_manager import GameManager
from .character import Character
from ..main import HostState


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

    # Thread coordination
    flow_running: bool = Field(default=False, description="Whether HostFlow is currently executing")
    awaiting_difficulty_decision: bool = Field(default=False, description="Whether GUI is waiting for user difficulty decision")
    current_difficulty: Optional[int] = Field(default=None, description="Current difficulty DC if awaiting decision")
    host_state: HostState = Field(default=None, description="Current difficulty DC if awaiting decision")



class InterfaceAgent:
    """
    Interface Agent - GUI component for D&D MAS.

    Manages:
    - GUI rendering and event handling
    - Thread-safe communication with HostFlow
    - MongoDB connection verification
    - Game state display (HP, Skills, Items, Location, NPC health)
    - Conversation history with speaker labels
    """

    def __init__(self):
        """Initialize the Interface Agent."""
        # Internal state
        self.state = InterfaceState()

        # Threading components
        self.to_flow_queue: queue.Queue = queue.Queue()
        self.from_flow_queue: queue.Queue = queue.Queue()
        self.shutdown_event: threading.Event = threading.Event()
        self.flow_thread: Optional[threading.Thread] = None

        # GUI components
        self.window: Optional[sg.Window] = None

        # MongoDB connection
        self.mongo_client: Optional[MongoClient] = None

    def check_mongodb_connection(self) -> bool:
        """
        Verify MongoDB connection on startup.

        Returns:
            True if connected successfully, False otherwise
        """
        try:
            # Attempt to connect with 2-second timeout
            client = MongoClient(
                MongoDBVectorSearchConfig.MONGO_URI,
                serverSelectionTimeoutMS=2000
            )

            # Force connection check
            client.admin.command('ping')

            self.mongo_client = client
            print("[InterfaceAgent] MongoDB connection successful")
            return True

        except Exception as e:
            sg.popup_error(
                f"MongoDB Connection Failed\n\n{str(e)}\n\n"
                "Please ensure MongoDB is running on localhost:27017\n"
                "(Docker Desktop or local MongoDB Community Server)",
                title="Database Error"
            )
            return False

    def PC_tab(self, char: Character, char_index: int) -> sg.Tab:
        """
        Create a tab for a single character (main character or companion).

        Args:
            char: Character object
            char_index: Index for unique key generation (0 for main, 1+ for companions)

        Returns:
            sg.Tab with character information
        """
        # Create unique keys for this character's widgets
        key_prefix = f"-CHAR{char_index}-"

        # Format spells list
        spells_text = "None"
        if char.spells:
            if isinstance(char.spells, list):
                # Handle list of dicts or list of strings
                spell_names = []
                for spell in char.spells:
                    if isinstance(spell, dict):
                        spell_names.append(spell.get("name", str(spell)))
                    else:
                        spell_names.append(str(spell))
                spells_text = ", ".join(spell_names) if spell_names else "None"
            else:
                spells_text = str(char.spells)

        # Format equipment/inventory
        inventory_text = "None"
        if char.equipment:
            if isinstance(char.equipment, list):
                equip_names = []
                for item in char.equipment:
                    if isinstance(item, dict):
                        equip_names.append(item.get("name", str(item)))
                    else:
                        equip_names.append(str(item))
                inventory_text = ", ".join(equip_names) if equip_names else "None"
            else:
                inventory_text = str(char.equipment)
        elif char.inventory:
            inventory_text = ", ".join(char.inventory)

        return sg.Tab(char.name, [
            [sg.Text("Character", font=("Helvetica", 12, "bold"))],
            [sg.Frame("Character Info", [
                [sg.Text(f"Name: {char.name}", key=key_prefix+"NAME", size=(25, 1))],
                [sg.Text(f"Class: {char.character_class} Lv.{char.level}", key=key_prefix+"CLASS", size=(25, 1))],
                [sg.Text(f"HP: {char.hp}/{char.max_hp}", key=key_prefix+"HP", size=(25, 1))],
                [sg.Text(f"AC: {char.ac}", key=key_prefix+"AC", size=(25, 1))],
                [sg.HorizontalSeparator()],
                [sg.Text(f"Location: {self.state.host_state.current_venue if self.state.host_state else 'Unknown'}",
                        key=key_prefix+"VENUE", size=(25, 2))],
                [sg.Text(f"Stage: {self.state.host_state.current_stage if self.state.host_state else 'Unknown'}",
                        key=key_prefix+"STAGE", size=(25, 2))],
            ])],
            [sg.Frame("Skills", [
                [sg.Multiline(
                    default_text=", ".join(char.skills) if char.skills else "None",
                    key=key_prefix+"SKILLS",
                    size=(25, 4),
                    disabled=True,
                    font=("Courier", 9),
                    background_color="#1E1E1E",
                    text_color="#FFFFFF"
                )]
            ])],
            [sg.Frame("Spells", [
                [sg.Multiline(
                    default_text=spells_text,
                    key=key_prefix+"SPELLS",
                    size=(25, 4),
                    disabled=True,
                    font=("Courier", 9),
                    background_color="#1E1E1E",
                    text_color="#FFFFFF"
                )]
            ])],
            [sg.Frame("Inventory", [
                [sg.Multiline(
                    default_text=inventory_text,
                    key=key_prefix+"ITEMS",
                    size=(25, 6),
                    disabled=True,
                    font=("Courier", 9),
                    background_color="#1E1E1E",
                    text_color="#FFFFFF"
                )]
            ])]
        ], key=key_prefix+"TAB")
    
    def initialize_PC(self) -> list:
        """
        Initialize PC column with placeholder or actual character data.

        Returns placeholder layout if host_state not available,
        otherwise creates tabs for all characters.
        """
        # Create a placeholder column that will be replaced when game loads
        placeholder_column = [
            [sg.Text("Loading Characters...", font=("Helvetica", 12, "bold"), key="-PC-LOADING-")],
            [sg.Frame("Waiting for Game Data", [
                [sg.Text("Game is initializing...", size=(25, 1))],
                [sg.Text("Characters will appear here", size=(25, 1))],
                [sg.Text("once the game loads.", size=(25, 1))],
            ], key="-PC-PLACEHOLDER-")]
        ]

        return placeholder_column



    def initialize_gui(self) -> sg.Window:
        """
        Create PySimpleGUI window layout.

        Returns:
            Initialized and finalized window object
        """
        # Set theme
        sg.theme('DarkBlue3')

        # Left Column - Player Character Information
        pc_column = self.initialize_PC() 

        # Center Column - Chat and Input
        center_column = [
            [sg.Text("Adventure Log", font=("Helvetica", 12, "bold"))],
            [sg.Frame("Narrative", [
                [sg.Multiline(
                    default_text="",
                    key="-CHAT-",
                    size=(60, 30),
                    autoscroll=True,
                    disabled=True,
                    font=("Courier", 10),
                    background_color="#1E1E1E",
                    text_color="#FFFFFF"
                )]
            ])],
            # Difficulty Check Panel (initially hidden)
            [sg.Frame("Action Check", [
                [sg.Text("", key="-ACTION-", size=(50, 1))],
                [
                    sg.Text("", key="-DC-", size=(20, 1)),
                    sg.Button("Roll d20", key="-ROLL-", visible=False),
                    sg.Text("", key="-ROLL-RESULT-", size=(20, 1))
                ]
            ], key="-CHECK-FRAME-", visible=False)],
            # User Input
            [sg.Frame("Your Action", [
                [
                    sg.Input(
                        key="-PROMPT-INPUT-",
                        size=(40, 1),
                        focus=True,
                        enable_events=False
                    ),
                    sg.Button("Submit", key="-SUBMIT-PROMPT-", bind_return_key=True),
                    sg.Button("Cancel Action", key="-CANCEL-CHECK-", visible=False)
                ]
            ])],
        ]

        # Right Column - NPC Information
        npc_column = [
            [sg.Text("Non-Player Characters", font=("Helvetica", 12, "bold"))],
            [sg.Frame("NPCs in Area", [
                [sg.Multiline(
                    default_text="No NPCs nearby",
                    key="-NPC-STATUS-",
                    size=(25, 35),
                    disabled=True,
                    font=("Courier", 9),
                    background_color="#1E1E1E",
                    text_color="#FFFFFF"
                )]
            ])],
        ]

        # Main Layout - Three Column Design
        layout = [
            # Title
            [sg.Text("D&D Multi-Agent System", font=("Helvetica", 16, "bold"), justification='center', expand_x=True)],
            # Three Columns
            [
                sg.Column(pc_column, vertical_alignment='top', element_justification='left'),
                sg.VerticalSeparator(),
                sg.Column(center_column, vertical_alignment='top', element_justification='center'),
                sg.VerticalSeparator(),
                sg.Column(npc_column, vertical_alignment='top', element_justification='right')
            ],
            # Status bar
            [sg.Text("Initializing...", key="-STATUS-", size=(120, 1),
                    relief=sg.RELIEF_SUNKEN)]
        ]

        # Create window
        window = sg.Window(
            f"D&D Adventure - {self.state.campaign}",
            layout,
            finalize=True,
            resizable=True,
            size=(1400, 900)
        )

        return window

    def start(self):
        """
        Main entry point - start GUI and game loop.

        This method:
        1. Checks MongoDB connection
        2. Initializes GUI window
        3. Displays welcome message
        4. Starts background flow thread
        5. Runs event loop
        """
        # Check MongoDB
        if not self.check_mongodb_connection():
            print("[InterfaceAgent] MongoDB connection failed, exiting")
            sys.exit(1)

        # Initialize GUI
        self.window = self.initialize_gui()

        # Initial welcome message will be replaced by start_narrative from GameManager
        # Display placeholder text
        self.window["-CHAT-"].update(
            "[SYSTEM] Loading game...\n\n"
            "Initializing campaign from MongoDB...\n"
        )

        # Start flow thread
        self.start_flow_thread()

        # Run event loop (blocks until window closes)
        self._event_loop()

        print("[InterfaceAgent] Application terminated")

    def start_flow_thread(self):
        """
        Start background thread running GameManager.

        The thread is created as daemon=True for auto-cleanup.
        """
        game_manager = GameManager(
            to_flow_queue=self.to_flow_queue,
            from_flow_queue=self.from_flow_queue,
            shutdown_event=self.shutdown_event
        )

        self.flow_thread = threading.Thread(
            target=game_manager.run,
            daemon=True,
            name="GameManagerThread"
        )
        self.flow_thread.start()
        print("[InterfaceAgent] GameManager thread started")

    def _event_loop(self):
        """
        Main GUI event loop (blocking).

        Handles:
        - User input events
        - Queue message processing
        - GUI updates
        """
        print("[InterfaceAgent] Entering event loop")

        while True:
            # Read with 100ms timeout (allows queue processing)
            event, values = self.window.read(timeout=100)

            # Process GUI events
            if event in (sg.WIN_CLOSED, "Exit"):
                print("[InterfaceAgent] Window close event received")
                break

            elif event == "-SUBMIT-PROMPT-":
                self._handle_prompt_submit(values["-PROMPT-INPUT-"])

            elif event == "-ROLL-":
                self._handle_difficulty_decision(True)

            elif event == "-CANCEL-CHECK-":
                self._handle_difficulty_decision(False)

            # Process flow messages (non-blocking)
            self._process_flow_messages()

            # Check shutdown
            if self.shutdown_event.is_set():
                break

        # Clean shutdown
        self._shutdown()

    def _handle_prompt_submit(self, prompt_text: str):
        """
        Handle Submit button click.

        Args:
            prompt_text: User's prompt from input field
        """
        if not prompt_text or not prompt_text.strip():
            sg.popup_error("Please enter an action", title="Empty Prompt")
            return

        # Update status
        self.window["-STATUS-"].update("Processing action...")

        # Disable input while processing
        self.window["-SUBMIT-PROMPT-"].update(disabled=True)
        self.window["-PROMPT-INPUT-"].update(disabled=True)

        # Set flow running flag
        self.state.flow_running = True

        # Send START_FLOW message to background thread
        self.to_flow_queue.put(create_message(
            MessageType.START_FLOW,
            {
                "prompt": prompt_text,
                "venue": self.state.host_state.current_venue,
                "stage": self.state.host_state.current_stage
            }
        ))

    def _handle_difficulty_decision(self, proceed: bool):
        """
        Handle difficulty check decision (Roll d20 or Cancel).

        Args:
            proceed: True to roll d20, False to cancel action
        """
        if not self.state.awaiting_difficulty_decision:
            return

        # Hide decision panel
        self.state.awaiting_difficulty_decision = False

        if proceed:
            # Perform d20 roll
            roll = randint(1, 20)

            # Display roll result
            self.window["-ROLL-RESULT-"].update(f"You rolled: {roll}")

            # Update status
            self.window["-STATUS-"].update("Resolving action...")

            # Disable roll button
            self.window["-ROLL-"].update(disabled=True)
            self.window["-CANCEL-CHECK-"].update(disabled=True)

            # Send ROLL_D20 message to flow thread
            self.to_flow_queue.put(create_message(
                MessageType.ROLL_D20,
                {"roll": roll}
            ))

        else:
            # User cancelled action
            # Hide difficulty check panel
            self.window["-CHECK-FRAME-"].update(visible=False)
            self.window["-ROLL-"].update(visible=False, disabled=False)
            self.window["-CANCEL-CHECK-"].update(visible=False)
            self.window["-ROLL-RESULT-"].update("")

            # Re-enable input
            self.window["-SUBMIT-PROMPT-"].update(disabled=False)
            self.window["-PROMPT-INPUT-"].update(disabled=False)
            self.window["-STATUS-"].update("Action cancelled. Ready for new action.")

            # Clear prompt field
            self.window["-PROMPT-INPUT-"].update("")

            # Send CANCEL_ACTION message to flow thread
            self.to_flow_queue.put(create_message(
                MessageType.CANCEL_ACTION,
                {}
            ))

            # Clear flow running flag
            self.state.flow_running = False

    def _process_flow_messages(self):
        """
        Non-blocking queue processing.

        Called every event loop iteration to handle messages
        from the flow thread.
        """
        while True:
            try:
                msg = self.from_flow_queue.get_nowait()
                self._handle_flow_message(msg)
            except queue.Empty:
                break

    def _handle_flow_message(self, msg: Dict[str, Any]):
        """
        Process message from flow thread.

        Args:
            msg: Message dict with type, data, timestamp
        """
        msg_type = msg.get("type")
        msg_data = msg.get("data", {})
        self.state.host_state = msg_data.get("state")
        if msg_type == MessageType.FLOW_READY:
            # Flow thread initialized - rebuild GUI with actual character tabs
            state = msg_data.get("state")
            if state:
                self.state.host_state = state
                # Rebuild window with actual character tabs
                print("[InterfaceAgent] Rebuilding GUI with character data")
                self._rebuild_window_with_characters()

            self.window["-STATUS-"].update("Ready for action")
            print("[InterfaceAgent] Flow thread ready")

        elif msg_type == MessageType.VALIDATION_ERROR:
            # Invalid prompt - display clarification message
            validation_msg = msg_data.get("message", "Invalid action")

            # Display validation error in chat
            self.window["-CHAT-"].update(self.window["-CHAT-"].get() + f"\n[SYSTEM] {validation_msg}\n\n")

            # Re-enable input
            self.window["-SUBMIT-PROMPT-"].update(disabled=False)
            self.window["-PROMPT-INPUT-"].update(disabled=False)
            self.window["-STATUS-"].update("Ready for action")

            # Clear prompt field
            self.window["-PROMPT-INPUT-"].update("")

            # Clear flow running flag
            self.state.flow_running = False

        elif msg_type == MessageType.REQUEST_DIFFICULTY_CHECK:
            # Display difficulty check panel
            action = msg_data.get("action", "Unknown action")
            dc = msg_data.get("dc", 10)
            skip_check = msg_data.get("skip_check", False)

            if skip_check:
                # Auto-pass/fail - flow continues automatically
                pass
            else:
                # Show difficulty check UI
                self._show_difficulty_check(action, dc)

        elif msg_type == MessageType.DISPLAY_NARRATIVE:
            # Display final narrative and update game state
            narrative = msg_data.get("narrative", "")
            conversation_history = msg_data.get("conversation_history", [])

            # Update conversation display with full history from GameState
            self._update_conversation_display(conversation_history)

            # Update character status (with null safety check)
            if self.state.host_state is not None and self.state.host_state.main_character is not None:
                self._update_character_status()

            # Reset UI to ready state
            self.window["-CHECK-FRAME-"].update(visible=False)
            self.window["-ROLL-"].update(visible=False, disabled=False)
            self.window["-CANCEL-CHECK-"].update(visible=False)
            self.window["-ROLL-RESULT-"].update("")
            self.window["-SUBMIT-PROMPT-"].update(disabled=False)
            self.window["-PROMPT-INPUT-"].update(disabled=False)
            self.window["-STATUS-"].update("Ready for action")

            # Clear prompt field
            self.window["-PROMPT-INPUT-"].update("")

            # Clear flow running flag
            self.state.flow_running = False

        elif msg_type == MessageType.FLOW_ERROR:
            # Flow execution error
            error = msg_data.get("error", "Unknown error")
            sg.popup_error(
                f"Flow Execution Error\n\n{error}\n\n"
                "Please try a different action.",
                title="Error"
            )

            # Reset UI
            self.window["-CHECK-FRAME-"].update(visible=False)
            self.window["-ROLL-"].update(visible=False, disabled=False)
            self.window["-CANCEL-CHECK-"].update(visible=False)
            self.window["-ROLL-RESULT-"].update("")
            self.window["-SUBMIT-PROMPT-"].update(disabled=False)
            self.window["-PROMPT-INPUT-"].update(disabled=False)
            self.window["-STATUS-"].update("Error - ready for new action")

            # Clear prompt field
            self.window["-PROMPT-INPUT-"].update("")

            # Clear flow running flag
            self.state.flow_running = False

    def _update_conversation_display(self, conversation_history: List[Dict]):
        """
        Update the chat window with conversation history from GameState.

        Args:
            conversation_history: List of conversation turns from GameState
        """
        # Format conversation history
        formatted_text = ""
        for turn in conversation_history:
            # Display user prompt
            formatted_text += f"[YOU] {turn['prompt']}\n\n"
            # Display narrative response
            formatted_text += f"[NARRATOR] {turn['narrative']}\n\n"

        # Update chat window
        self.window["-CHAT-"].update(formatted_text)

    def _show_difficulty_check(self, action: str, dc: int):
        """
        Display difficulty check UI.

        Args:
            action: Action description
            dc: Difficulty class (1-20)
        """
        # Update difficulty text (combined action + DC)
        difficulty_text = f"Action: {action}\nDifficulty Check (DC): {dc}"
        self.window["-DIFFICULTY-TEXT-"].update(difficulty_text)

        # Show difficulty check panel
        self.window["-CHECK-FRAME-"].update(visible=True)
        self.window["-ROLL-"].update(visible=True, disabled=False)
        self.window["-CANCEL-CHECK-"].update(visible=True)

        # Clear previous roll result
        self.window["-ROLL-RESULT-"].update("")

        # Update status
        self.window["-STATUS-"].update("Waiting for difficulty check")

        # Set awaiting flag
        self.state.awaiting_difficulty_decision = True
        self.state.current_difficulty = dc

    def _rebuild_window_with_characters(self):
        """
        Rebuild the entire window with actual character tabs.
        Called when FLOW_READY message arrives with host_state.
        """
        if not self.state.host_state:
            return

        # Store current window position
        location = self.window.current_location() if self.window else (None, None)

        # Close old window
        if self.window:
            self.window.close()

        # Create new window with actual character data
        sg.theme('DarkBlue3')

        # Left Column - Player Characters with tabs
        char_list = []
        if self.state.host_state.main_character:
            char_list.append(self.state.host_state.main_character)
        char_list.extend(self.state.host_state.companions)

        tabs = []
        for idx, char in enumerate(char_list):
            tabs.append(self.PC_tab(char, idx))

        pc_column = [
            [sg.Text("Player Characters", font=("Helvetica", 12, "bold"))],
            [sg.TabGroup([tabs], key='-PC-TABGROUP-', enable_events=True)]
        ]

        # Center Column - Chat and Input (unchanged)
        center_column = [
            [sg.Text("Adventure Log", font=("Helvetica", 12, "bold"))],
            [sg.Frame("Narrative", [
                [sg.Multiline(
                    default_text="",
                    key="-CHAT-",
                    size=(60, 30),
                    autoscroll=True,
                    disabled=True,
                    font=("Courier", 10),
                    background_color="#1E1E1E",
                    text_color="#FFFFFF"
                )]
            ])],
            [sg.Frame("Difficulty Check", [
                [sg.Text("", key="-DIFFICULTY-TEXT-", size=(60, 2))],
                [sg.Text("", key="-ROLL-RESULT-", size=(60, 1), font=("Helvetica", 12, "bold"))],
                [sg.Button("Roll d20", key="-ROLL-", size=(10, 1), disabled=False, visible=False),
                 sg.Button("Cancel", key="-CANCEL-CHECK-", size=(10, 1), visible=False)]
            ], key="-CHECK-FRAME-", visible=False)],
            [sg.Input(key="-PROMPT-INPUT-", size=(50, 1), disabled=False, enable_events=True),
             sg.Button("Submit", key="-SUBMIT-PROMPT-", size=(10, 1), disabled=False)]
        ]

        # Right Column - NPCs (unchanged)
        npc_column = [
            [sg.Text("Non-Player Characters", font=("Helvetica", 12, "bold"))],
            [sg.Frame("NPCs in Area", [
                [sg.Multiline(
                    default_text="No NPCs nearby",
                    key="-NPC-STATUS-",
                    size=(25, 35),
                    disabled=True,
                    font=("Courier", 9),
                    background_color="#1E1E1E",
                    text_color="#FFFFFF"
                )]
            ])],
        ]

        # Complete layout
        layout = [
            [sg.Text("D&D Multi-Agent System", font=("Helvetica", 14, "bold"), justification="center", expand_x=True)],
            [
                sg.Column(pc_column, vertical_alignment='top'),
                sg.VerticalSeparator(),
                sg.Column(center_column, vertical_alignment='top'),
                sg.VerticalSeparator(),
                sg.Column(npc_column, vertical_alignment='top')
            ],
            [sg.Text("Initializing...", key="-STATUS-", size=(100, 1))]
        ]

        # Create new window
        self.window = sg.Window("D&D Adventure", layout, size=(1400, 900), finalize=True, location=location)
        self.window["-PROMPT-INPUT-"].bind("<Return>", "_ENTER")

        print("[DEBUG] Window rebuilt with character tabs")

    def _update_character_status(self):
        """
        Update character status display for all characters using HostState.
        """
        if not self.state.host_state:
            return

        # Update each character tab
        char_list = []
        if self.state.host_state.main_character:
            char_list.append((0, self.state.host_state.main_character))

        for idx, companion in enumerate(self.state.host_state.companions):
            char_list.append((idx + 1, companion))

        for char_index, char in char_list:
            key_prefix = f"-CHAR{char_index}-"

            # Update character info
            try:
                self.window[key_prefix + "NAME"].update(f"Name: {char.name}")
                self.window[key_prefix + "CLASS"].update(f"Class: {char.character_class} Lv.{char.level}")
                self.window[key_prefix + "HP"].update(f"HP: {char.hp}/{char.max_hp}")
                self.window[key_prefix + "AC"].update(f"AC: {char.ac}")
                self.window[key_prefix + "VENUE"].update(f"Location: {self.state.host_state.current_venue}")
                self.window[key_prefix + "STAGE"].update(f"Stage: {self.state.host_state.current_stage}")

                # Update skills
                skills_text = ", ".join(char.skills) if char.skills else "None"
                self.window[key_prefix + "SKILLS"].update(skills_text)

                # Update spells
                spells_text = "None"
                if char.spells:
                    if isinstance(char.spells, list):
                        spell_names = []
                        for spell in char.spells:
                            if isinstance(spell, dict):
                                spell_names.append(spell.get("name", str(spell)))
                            else:
                                spell_names.append(str(spell))
                        spells_text = ", ".join(spell_names) if spell_names else "None"
                self.window[key_prefix + "SPELLS"].update(spells_text)

                # Update inventory
                inventory_text = "None"
                if char.equipment:
                    if isinstance(char.equipment, list):
                        equip_names = []
                        for item in char.equipment:
                            if isinstance(item, dict):
                                equip_names.append(item.get("name", str(item)))
                            else:
                                equip_names.append(str(item))
                        inventory_text = ", ".join(equip_names) if equip_names else "None"
                elif char.inventory:
                    inventory_text = ", ".join(char.inventory)
                self.window[key_prefix + "ITEMS"].update(inventory_text)

            except KeyError as e:
                # Key doesn't exist yet (tabs not created)
                print(f"[DEBUG] Cannot update {char.name} - tabs not created yet: {e}")
                pass

    def _update_npc_status(self, npcs: List[Dict[str, Any]]):
        """
        Update NPC status display.

        Args:
            npcs: List of NPC dicts with name, hp, max_hp, and optional additional info
        """
        self.state.active_npcs = npcs

        if not npcs:
            self.window["-NPC-STATUS-"].update("No NPCs nearby")
        else:
            npc_text = ""
            for npc in npcs:
                name = npc.get("name", "Unknown")
                hp = npc.get("hp", "?")
                max_hp = npc.get("max_hp", "?")
                status = npc.get("status", "")
                description = npc.get("description", "")

                # Add NPC header
                npc_text += f"{'=' * 23}\n"
                npc_text += f"{name}\n"
                npc_text += f"{'=' * 23}\n"
                npc_text += f"HP: {hp}/{max_hp}\n"

                # Add status if available
                if status:
                    npc_text += f"Status: {status}\n"

                # Add description if available (truncated)
                if description:
                    desc_short = description[:50] + "..." if len(description) > 50 else description
                    npc_text += f"{desc_short}\n"

                npc_text += "\n"

            self.window["-NPC-STATUS-"].update(npc_text.strip())

    def _shutdown(self):
        """
        Clean shutdown sequence.

        Steps:
        1. Signal background thread
        2. Wait for thread join
        3. Close MongoDB
        4. Close GUI window
        """
        print("[InterfaceAgent] Initiating shutdown")

        # Set shutdown flag
        self.shutdown_event.set()

        # Send shutdown message to flow thread
        self.to_flow_queue.put(create_message(
            MessageType.SHUTDOWN,
            {}
        ))

        # Wait for thread with timeout
        if self.flow_thread and self.flow_thread.is_alive():
            print("[InterfaceAgent] Waiting for flow thread to terminate...")
            self.flow_thread.join(timeout=5.0)
            if self.flow_thread.is_alive():
                print("[InterfaceAgent] Warning: Flow thread did not terminate within timeout")

        # Close MongoDB
        if self.mongo_client:
            self.mongo_client.close()
            print("[InterfaceAgent] MongoDB connection closed")

        # Close window
        if self.window:
            self.window.close()
            print("[InterfaceAgent] Window closed")


def main():
    """Main entry point for Interface Agent."""
    print("=" * 60)
    print("D&D Multi-Agent System - Interface Agent")
    print("=" * 60)

    agent = InterfaceAgent()
    agent.start()


if __name__ == "__main__":
    main()
