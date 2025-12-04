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

import queue
import threading
import sys
from typing import Optional, List, Dict, Any
from random import randint

import PySimpleGUI as sg
from pymongo import MongoClient

from ..tools.mongodb_vector_tools import MongoDBVectorSearchConfig
from .message_types import MessageType, create_message
from .game_manager import GameManager
from .models import ConversationEntry, InterfaceState


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

    def initialize_gui(self) -> sg.Window:
        """
        Create PySimpleGUI window layout.

        Returns:
            Initialized and finalized window object
        """
        # Set theme
        sg.theme('DarkBlue3')

        # Layout structure
        layout = [
            # Title
            [sg.Text("D&D Multi-Agent System", font=("Helvetica", 16, "bold"))],

            # Character Status Panel
            [sg.Frame("Character Status", [
                [
                    sg.Text(f"Name: {self.state.player}", key="-PLAYER-NAME-", size=(20, 1)),
                    sg.Text(f"Class: {self.state.player_class}", key="-PLAYER-CLASS-", size=(20, 1)),
                    sg.Text(f"HP: {self.state.character_hp}/{self.state.character_max_hp}",
                           key="-HP-", size=(15, 1))
                ],
                [
                    sg.Text(f"Location: {self.state.current_venue}",
                           key="-VENUE-", size=(40, 1)),
                    sg.Text(f"Stage: {self.state.current_stage}",
                           key="-STAGE-", size=(40, 1))
                ],
                [
                    sg.Text("Skills:", size=(8, 1)),
                    sg.Text(", ".join(self.state.character_skills) if self.state.character_skills else "None",
                           key="-SKILLS-", size=(70, 1))
                ],
                [
                    sg.Text("Items:", size=(8, 1)),
                    sg.Text(", ".join(self.state.character_items) if self.state.character_items else "None",
                           key="-ITEMS-", size=(70, 1))
                ]
            ])],

            # NPC Status Panel
            [sg.Frame("NPCs in Area", [
                [sg.Multiline(
                    default_text="No NPCs nearby",
                    key="-NPC-STATUS-",
                    size=(90, 3),
                    disabled=True,
                    font=("Courier", 9),
                    background_color="#1E1E1E",
                    text_color="#FFFFFF"
                )]
            ])],

            # Chat History (scrollable)
            [sg.Frame("Adventure Log", [
                [sg.Multiline(
                    default_text="",
                    key="-CHAT-",
                    size=(90, 18),
                    autoscroll=True,
                    disabled=True,
                    font=("Courier", 10),
                    background_color="#1E1E1E",
                    text_color="#FFFFFF"
                )]
            ])],

            # Difficulty Check Panel (initially hidden)
            [sg.Frame("Action Check", [
                [sg.Text("", key="-ACTION-", size=(70, 1))],
                [
                    sg.Text("", key="-DC-", size=(25, 1)),
                    sg.Button("Roll d20", key="-ROLL-", visible=False),
                    sg.Text("", key="-ROLL-RESULT-", size=(30, 1))
                ]
            ], key="-CHECK-FRAME-", visible=False)],

            # User Input
            [sg.Frame("Your Action", [
                [
                    sg.Input(
                        key="-PROMPT-INPUT-",
                        size=(70, 1),
                        focus=True,
                        enable_events=False
                    ),
                    sg.Button("Submit", key="-SUBMIT-PROMPT-", bind_return_key=True),
                    sg.Button("Cancel Action", key="-CANCEL-CHECK-", visible=False)
                ]
            ])],

            # Status bar
            [sg.Text("Initializing...", key="-STATUS-", size=(80, 1),
                    relief=sg.RELIEF_SUNKEN)]
        ]

        # Create window
        window = sg.Window(
            f"D&D Adventure - {self.state.campaign}",
            layout,
            finalize=True,
            resizable=True,
            size=(950, 850)
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
                "venue": self.state.current_venue,
                "stage": self.state.current_stage
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

        if msg_type == MessageType.FLOW_READY:
            # Flow thread initialized
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
            hp = msg_data.get("hp", self.state.character_hp)
            max_hp = msg_data.get("max_hp", self.state.character_max_hp)
            venue = msg_data.get("venue", self.state.current_venue)
            stage = msg_data.get("stage", self.state.current_stage)
            conversation_history = msg_data.get("conversation_history", [])
            game_over = msg_data.get("game_over", False)
            victory = msg_data.get("victory", False)

            # Update conversation display with full history from GameState
            self._update_conversation_display(conversation_history)

            # Update character status
            self._update_character_status(hp, max_hp, venue, stage)

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
        # Update action and DC text
        self.window["-ACTION-"].update(f"Action: {action}")
        self.window["-DC-"].update(f"Difficulty Check (DC): {dc}")

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

    def _update_character_status(self, hp: int, max_hp: int, venue: str, stage: str):
        """
        Update character status display.

        Args:
            hp: Current HP
            max_hp: Maximum HP
            venue: Current location
            stage: Current story stage
        """
        self.state.character_hp = hp
        self.state.character_max_hp = max_hp
        self.state.current_venue = venue
        self.state.current_stage = stage

        # Update GUI elements
        self.window["-HP-"].update(f"HP: {hp}/{max_hp}")
        self.window["-VENUE-"].update(f"Location: {venue}")
        self.window["-STAGE-"].update(f"Stage: {stage}")

    def _update_npc_status(self, npcs: List[Dict[str, Any]]):
        """
        Update NPC status display.

        Args:
            npcs: List of NPC dicts with name, hp, max_hp
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
                npc_text += f"{name}: HP {hp}/{max_hp}\n"
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
