"""
PySimpleGUI-based interface for D&D Multi-Agent System.

This module provides the main GUI interface that runs in the main thread
and communicates with the HostFlow background thread via queues.
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
from .flow_runner import run_flow_in_thread


class DnDGUIInterface:
    """
    PySimpleGUI-based interface for D&D Multi-Agent System.

    Manages:
    - GUI rendering and event handling
    - Thread-safe communication with HostFlow
    - MongoDB connection verification
    - Game state display
    """

    def __init__(self):
        """Initialize the GUI interface."""
        # Threading components
        self.to_flow_queue: queue.Queue = queue.Queue()
        self.from_flow_queue: queue.Queue = queue.Queue()
        self.shutdown_event: threading.Event = threading.Event()
        self.flow_thread: Optional[threading.Thread] = None

        # GUI components
        self.window: Optional[sg.Window] = None

        # Game state (synchronized from HostState)
        self.current_hp: int = 20
        self.max_hp: int = 20
        self.current_venue: str = "Town Square"
        self.current_stage: str = "Arrival and Investigation"

        # Chat history
        self.chat_history: List[Dict[str, str]] = []

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
            print("[GUI] MongoDB connection successful")
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
                    sg.Text(f"HP: {self.current_hp}/{self.max_hp}",
                           key="-HP-", size=(15, 1)),
                    sg.Text(f"Location: {self.current_venue}",
                           key="-VENUE-", size=(40, 1))
                ]
            ])],

            # Chat History (scrollable)
            [sg.Frame("Adventure Log", [
                [sg.Multiline(
                    default_text="",
                    key="-CHAT-",
                    size=(90, 22),
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
                        key="-PROMPT-",
                        size=(70, 1),
                        focus=True,
                        enable_events=False
                    ),
                    sg.Button("Submit", key="-SUBMIT-", bind_return_key=True),
                    sg.Button("Cancel Action", key="-CANCEL-", visible=False)
                ]
            ])],

            # Status bar
            [sg.Text("Initializing...", key="-STATUS-", size=(80, 1),
                    relief=sg.RELIEF_SUNKEN)]
        ]

        # Create window
        window = sg.Window(
            "D&D Adventure",
            layout,
            finalize=True,
            resizable=True,
            size=(950, 750)
        )

        return window

    def start_flow_thread(self):
        """
        Start background thread running HostFlow.

        The thread is created as daemon=True for auto-cleanup.
        """
        self.flow_thread = threading.Thread(
            target=run_flow_in_thread,
            args=(self.to_flow_queue, self.from_flow_queue, self.shutdown_event),
            daemon=True,
            name="FlowThread"
        )
        self.flow_thread.start()
        print("[GUI] Flow thread started")

    def run_event_loop(self):
        """
        Main event loop (blocking).

        Handles:
        - User input events
        - Queue message processing
        - GUI updates
        """
        print("[GUI] Entering event loop")

        while True:
            # Read with 100ms timeout (allows queue processing)
            event, values = self.window.read(timeout=100)

            # Process GUI events
            if event in (sg.WIN_CLOSED, "Exit"):
                print("[GUI] Window close event received")
                break

            elif event == "-SUBMIT-":
                self.handle_submit(values["-PROMPT-"])

            elif event == "-ROLL-":
                self.handle_roll()

            elif event == "-CANCEL-":
                self.handle_cancel()

            # Process flow messages (non-blocking)
            self.process_flow_messages()

            # Check shutdown
            if self.shutdown_event.is_set():
                break

        # Clean shutdown
        self.shutdown()

    def handle_submit(self, prompt_text: str):
        """
        Handle Submit button click.

        Args:
            prompt_text: User's prompt from input field
        """
        if not prompt_text or not prompt_text.strip():
            sg.popup_error("Please enter an action", title="Empty Prompt")
            return

        # Display user's prompt in chat
        self.display_chat_message("YOU", prompt_text)

        # Update status
        self.window["-STATUS-"].update("Processing action...")

        # Disable input while processing
        self.window["-SUBMIT-"].update(disabled=True)
        self.window["-PROMPT-"].update(disabled=True)

        # Send START_FLOW message to background thread
        self.to_flow_queue.put(create_message(
            MessageType.START_FLOW,
            {
                "prompt": prompt_text,
                "venue": self.current_venue,
                "stage": self.current_stage
            }
        ))

    def handle_roll(self):
        """Handle Roll d20 button click."""
        # Generate random d20 roll
        roll = randint(1, 20)

        # Display roll result
        self.window["-ROLL-RESULT-"].update(f"You rolled: {roll}")
        self.display_chat_message("SYSTEM", f"You rolled a d20: {roll}")

        # Update status
        self.window["-STATUS-"].update("Resolving action...")

        # Disable roll button
        self.window["-ROLL-"].update(disabled=True)
        self.window["-CANCEL-"].update(disabled=True)

        # Send ROLL_D20 message to flow thread
        self.to_flow_queue.put(create_message(
            MessageType.ROLL_D20,
            {"roll": roll}
        ))

    def handle_cancel(self):
        """Handle Cancel Action button click."""
        # Hide difficulty check panel
        self.window["-CHECK-FRAME-"].update(visible=False)
        self.window["-ROLL-"].update(visible=False, disabled=False)
        self.window["-CANCEL-"].update(visible=False)
        self.window["-ROLL-RESULT-"].update("")

        # Re-enable prompt input
        self.window["-SUBMIT-"].update(disabled=False)
        self.window["-PROMPT-"].update(disabled=False)
        self.window["-STATUS-"].update("Action cancelled. Ready for new action.")

        # Clear prompt field
        self.window["-PROMPT-"].update("")

        # Display cancellation message
        self.display_chat_message("SYSTEM", "Action cancelled.")

        # Send CANCEL_ACTION message to flow thread
        self.to_flow_queue.put(create_message(
            MessageType.CANCEL_ACTION,
            {}
        ))

    def process_flow_messages(self):
        """
        Non-blocking queue processing.

        Called every event loop iteration to handle messages
        from the flow thread.
        """
        while True:
            try:
                msg = self.from_flow_queue.get_nowait()
                self.handle_flow_message(msg)
            except queue.Empty:
                break

    def handle_flow_message(self, msg: Dict[str, Any]):
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
            print("[GUI] Flow thread ready")

        elif msg_type == MessageType.VALIDATION_ERROR:
            # Invalid prompt - display clarification message
            validation_msg = msg_data.get("message", "Invalid action")
            self.display_chat_message("NARRATOR", validation_msg)

            # Re-enable input
            self.window["-SUBMIT-"].update(disabled=False)
            self.window["-PROMPT-"].update(disabled=False)
            self.window["-STATUS-"].update("Ready for action")

            # Clear prompt field
            self.window["-PROMPT-"].update("")

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
                self.show_difficulty_check(action, dc)

        elif msg_type == MessageType.DISPLAY_NARRATIVE:
            # Display final narrative and update game state
            narrative = msg_data.get("narrative", "")
            hp = msg_data.get("hp", self.current_hp)
            max_hp = msg_data.get("max_hp", self.max_hp)
            venue = msg_data.get("venue", self.current_venue)

            # Display narrative
            self.display_chat_message("NARRATOR", narrative)

            # Update character status
            self.update_character_status(hp, max_hp, venue)

            # Reset UI to ready state
            self.window["-CHECK-FRAME-"].update(visible=False)
            self.window["-ROLL-"].update(visible=False, disabled=False)
            self.window["-CANCEL-"].update(visible=False)
            self.window["-ROLL-RESULT-"].update("")
            self.window["-SUBMIT-"].update(disabled=False)
            self.window["-PROMPT-"].update(disabled=False)
            self.window["-STATUS-"].update("Ready for action")

            # Clear prompt field
            self.window["-PROMPT-"].update("")

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
            self.window["-CANCEL-"].update(visible=False)
            self.window["-ROLL-RESULT-"].update("")
            self.window["-SUBMIT-"].update(disabled=False)
            self.window["-PROMPT-"].update(disabled=False)
            self.window["-STATUS-"].update("Error - ready for new action")

            # Clear prompt field
            self.window["-PROMPT-"].update("")

    def display_chat_message(self, speaker: str, text: str):
        """
        Add message to chat history and update display.

        Args:
            speaker: "NARRATOR", "YOU", "SYSTEM", or NPC name
            text: Message content
        """
        # Store in history
        self.chat_history.append({"speaker": speaker, "text": text})

        # Format with speaker labels
        if speaker == "NARRATOR":
            formatted = f"[NARRATOR] {text}\n\n"
        elif speaker == "YOU":
            formatted = f"[YOU] {text}\n\n"
        elif speaker == "SYSTEM":
            formatted = f"[SYSTEM] {text}\n\n"
        else:
            # NPC name
            formatted = f"[{speaker.upper()}] {text}\n\n"

        # Append to chat window
        current = self.window["-CHAT-"].get()
        self.window["-CHAT-"].update(current + formatted)

    def show_difficulty_check(self, action: str, dc: int):
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
        self.window["-CANCEL-"].update(visible=True)

        # Clear previous roll result
        self.window["-ROLL-RESULT-"].update("")

        # Update status
        self.window["-STATUS-"].update("Waiting for difficulty check")

    def update_character_status(self, hp: int, max_hp: int, venue: str):
        """
        Update character status display.

        Args:
            hp: Current HP
            max_hp: Maximum HP
            venue: Current location
        """
        self.current_hp = hp
        self.max_hp = max_hp
        self.current_venue = venue

        # Update GUI elements
        self.window["-HP-"].update(f"HP: {hp}/{max_hp}")
        self.window["-VENUE-"].update(f"Location: {venue}")

    def shutdown(self):
        """
        Clean shutdown sequence.

        Steps:
        1. Signal background thread
        2. Wait for thread join
        3. Close MongoDB
        4. Close GUI window
        """
        print("[GUI] Initiating shutdown")

        # Set shutdown flag
        self.shutdown_event.set()

        # Send shutdown message to flow thread
        self.to_flow_queue.put(create_message(
            MessageType.SHUTDOWN,
            {}
        ))

        # Wait for thread with timeout
        if self.flow_thread and self.flow_thread.is_alive():
            print("[GUI] Waiting for flow thread to terminate...")
            self.flow_thread.join(timeout=5.0)
            if self.flow_thread.is_alive():
                print("[GUI] Warning: Flow thread did not terminate within timeout")

        # Close MongoDB
        if self.mongo_client:
            self.mongo_client.close()
            print("[GUI] MongoDB connection closed")

        # Close window
        if self.window:
            self.window.close()
            print("[GUI] Window closed")


def main():
    """Main entry point for GUI interface."""
    print("=" * 60)
    print("D&D Multi-Agent System - GUI Interface")
    print("=" * 60)

    interface = DnDGUIInterface()

    # Check MongoDB connection
    if not interface.check_mongodb_connection():
        print("[GUI] MongoDB connection failed, exiting")
        sys.exit(1)

    # Initialize GUI
    interface.window = interface.initialize_gui()

    # Display welcome message
    interface.display_chat_message(
        "NARRATOR",
        "Welcome to Humantown: Rescue from the Town of Slimes!\n\n"
        "You find yourself on the outskirts of a peculiar settlement. "
        "The buildings seem normal, but something feels... off. "
        "The townsfolk move with an unusual fluidity.\n\n"
        "Type your action below and press Submit to begin your adventure."
    )

    # Start flow thread
    interface.start_flow_thread()

    # Run event loop (blocks until window closes)
    interface.run_event_loop()

    print("[GUI] Application terminated")


if __name__ == "__main__":
    main()
