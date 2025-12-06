"""
Interface Agent V2 - GUI component for D&D Multi-Agent System.

This version uses the new HostManager-based message-passing architecture
with the Blackboard pattern for state management.

Architecture:
- GUI Thread: PySimpleGUI event loop (main thread)
- HostManager Thread: Message processing and agent execution (background thread)
- Communication: Message callbacks and thread-safe queues
"""

from datetime import datetime
import queue
import threading
import sys
from typing import Optional, List, Dict, Any
from random import randint

import PySimpleGUI as sg
from pydantic import BaseModel, Field

from dnd_mas_host.manager.host_manager import HostManager
from dnd_mas_host.interface.message_types import Message, MessageType, create_message
from dnd_mas_host.interface.consequence_applicator import ConsequenceApplicator
from dnd_mas_host.interface.character import Character


class InterfaceStateV2(BaseModel):
    """
    Internal state for Interface Agent V2.

    Tracks GUI state including game context and thread coordination.
    """
    # Game state (synchronized from HostManager)
    campaign: str = Field(default="", description="Campaign name")
    player_name: str = Field(default="", description="Player character name")
    player_hp: int = Field(default=0, description="Current HP")
    player_max_hp: int = Field(default=0, description="Maximum HP")
    current_stage: str = Field(default="", description="Current story stage")
    current_venue: str = Field(default="", description="Current location")

    # Thread coordination
    flow_running: bool = Field(default=False, description="Whether flow is currently executing")
    awaiting_roll: bool = Field(default=False, description="Whether GUI is waiting for user to roll")
    current_difficulty: Optional[int] = Field(default=None, description="Current difficulty DC if awaiting roll")

    # Conversation history (for display)
    conversation_history: List[Dict[str, str]] = Field(default_factory=list, description="Conversation turns")


class InterfaceAgentV2:
    """
    Interface Agent V2 - GUI component using HostManager architecture.

    Manages:
    - GUI rendering and event handling
    - Communication with HostManager via message callbacks
    - Game state display (HP, Location, NPCs)
    - Conversation history
    """

    CAMPAIGN_NAME = "Humantown: Rescue from the Town of Slimes"

    def __init__(self):
        """Initialize the Interface Agent V2."""
        # Internal state
        self.state = InterfaceStateV2()

        # HostManager (created in start())
        self.host_manager: Optional[HostManager] = None
        self.host_thread: Optional[threading.Thread] = None

        # Message queue for GUI updates (from HostManager)
        self.gui_queue: queue.Queue = queue.Queue()

        # Shutdown event
        self.shutdown_event = threading.Event()

        # GUI components
        self.window: Optional[sg.Window] = None

    def _handle_host_message(self, msg: Message):
        """
        Callback for messages from HostManager.

        This is called from the HostManager thread, so we queue
        messages for the GUI thread to process.

        Args:
            msg: Message from HostManager
        """
        self.gui_queue.put(msg)

    def initialize_gui(self) -> sg.Window:
        """
        Create PySimpleGUI window layout.

        Returns:
            Initialized and finalized window object
        """
        sg.theme('DarkBlue3')

        # Left Column - Player Character Information
        pc_column = pc_column = [[ sg.TabGroup([[  # <-- outer list = layout (list of rows)
    sg.Tab('Player Character', [[ sg.Frame("Character Info", [
        [sg.Text("Name: Loading...", key="-PC-NAME-", size=(25, 1))],
        [sg.Text("HP: --/--", key="-PC-HP-", size=(25, 1))],
        [sg.Text("Class: Loading...", key="-PC-Class-", size=(25, 1))],
        [sg.Text("Level: --/--", key="-PC-Level-", size=(25, 1))],
        [sg.HorizontalSeparator()],
        [sg.Text("Stage: Loading...", key="-PC-STAGE-", size=(25, 2))],
        [sg.Text("Location: Loading...", key="-PC-VENUE-", size=(25, 2))],
    ]) ]]),

    sg.Tab('Party Member 1', [[ sg.Frame("Character Info", [
        [sg.Text("Name: Loading...", key="-PC1-NAME-", size=(25, 1))],
        [sg.Text("HP: --/--", key="-PC1-HP-", size=(25, 1))],
        [sg.Text("Class: Loading...", key="-PC1-Class-", size=(25, 1))],
        [sg.Text("Level: --/--", key="-PC1-Level-", size=(25, 1))],
        [sg.HorizontalSeparator()],
        [sg.Text("Stage: Loading...", key="-PC1-STAGE-", size=(25, 2))],
        [sg.Text("Location: Loading...", key="-PC1-VENUE-", size=(25, 2))],
    ]) ]]),

    sg.Tab('Party Member 2', [[ sg.Frame("Character Info", [
        [sg.Text("Name: Loading...", key="-PC2-NAME-", size=(25, 1))],
        [sg.Text("HP: --/--", key="-PC2-HP-", size=(25, 1))],
        [sg.Text("Class: Loading...", key="-PC2-Class-", size=(25, 1))],
        [sg.Text("Level: --/--", key="-PC2-Level-", size=(25, 1))],
        [sg.HorizontalSeparator()],
        [sg.Text("Stage: Loading...", key="-PC2-STAGE-", size=(25, 2))],
        [sg.Text("Location: Loading...", key="-PC2-VENUE-", size=(25, 2))],
    ]) ]]),

]], key='-TABGROUP-') ]]  # <-- close the row list and outer layout list

        # Center Column - Chat and Input
        center_column = [
            [sg.Text("Adventure Log", font=("Helvetica", 12, "bold"))],
            [sg.Frame("Narrative", [
                [sg.Multiline(
                    default_text="Initializing game...\n",
                    key="-CHAT-",
                    size=(60, 25),
                    autoscroll=True,
                    disabled=True,
                    font=("Courier", 10),
                    background_color="#1E1E1E",
                    text_color="#FFFFFF"
                )]
            ],   size=(500, 500))],
            # Difficulty Check Panel (initially hidden)
            [sg.Frame("Difficulty Check", [
                [sg.Text("", key="-DC-TEXT-", size=(40, 2))],
                [
                    sg.Button("Roll d20", key="-ROLL-", visible=False),
                    sg.Text("", key="-ROLL-RESULT-", size=(40, 1), font=("Helvetica", 12, "bold")),
                    sg.Button("Cancel", key="-CANCEL-", visible=False)
                ]
            ], key="-CHECK-FRAME-", visible=False)],
            # User Input
            [sg.Frame("Your Action", [
                [
                    sg.Input(
                        key="-PROMPT-INPUT-",
                        size=(45, 1),
                        focus=True
                    ),
                    sg.Button("Submit", key="-SUBMIT-", bind_return_key=True)
                ]
            ])],
        ]
        

        # Right Column - NPC Information
        npc_column = [
            [sg.Text("NPCs in Area", font=("Helvetica", 12, "bold"))],
            [sg.Frame("Non-Player Characters", [
                [sg.Multiline(
                    default_text="No NPCs nearby",
                    key="-NPC-STATUS-",
                    size=(25, 30),
                    disabled=True,
                    font=("Courier", 9),
                    background_color="#1E1E1E",
                    text_color="#FFFFFF"
                )]
            ])],
        ]

        # Main Layout
        layout = [
            [sg.Text("D&D Multi-Agent System (v2)", font=("Helvetica", 16, "bold"), justification='center', expand_x=True)],
            [
                sg.Column(pc_column, vertical_alignment='top',   size=(600, 700)),
                sg.VerticalSeparator(),
                sg.Column(center_column, vertical_alignment='top',   size=(600, 700)),
                sg.VerticalSeparator(),
                sg.Column(npc_column, vertical_alignment='top',   size=(600, 700))
            ],
            [sg.Text("Initializing...", key="-STATUS-", size=(100, 1), relief=sg.RELIEF_SUNKEN)],
            [sg.Text("Initializing...", key="-PHRASE-", size=(100, 1), relief=sg.RELIEF_SUNKEN)]
        ]

        window = sg.Window(
            "D&D Adventure - Message-Passing Architecture",
            layout,
            finalize=True,
            resizable=True,
            size=(1200, 800)
        )

        return window

    def start(self):
        """
        Main entry point - start GUI and game loop.

        Steps:
        1. Initialize GUI window
        2. Create and start HostManager in background thread
        3. Run event loop
        """
        print("[InterfaceAgentV2] Starting...")

        # Initialize GUI
        self.window = self.initialize_gui()

        # Create HostManager
        try:
            self.host_manager = HostManager(
                campaign_name=self.CAMPAIGN_NAME,
                interface_callback=self._handle_host_message
            )

            # Get initial game context
            context = self.host_manager.get_game_context_summary()
            self.state.campaign = context.get("campaign", "")
            self.state.player_name = context.get("player", "")
            self.state.player_hp = context.get("player_hp", 0)
            self.state.player_max_hp = context.get("player_max_hp", 0)
            self.state.current_stage = context.get("current_stage", "")
            self.state.current_venue = context.get("current_venue", "")

            # Update GUI with initial state
            self._update_character_display()

            # Get and display start narrative
            start_narrative = self.host_manager.get_start_narrative()
            self._append_chat(f"[NARRATOR]\n{start_narrative}\n")

            self.window["-STATUS-"].update("Ready for action")

        except Exception as e:
            sg.popup_error(
                f"Failed to initialize game:\n\n{str(e)}\n\n"
                "Please ensure MongoDB is running.",
                title="Initialization Error"
            )
            self.window.close()
            return

        # Start HostManager in background thread
        self.host_thread = threading.Thread(
            target=self.host_manager.run,
            daemon=True,
            name="HostManagerThread"
        )
        self.host_thread.start()
        print("[InterfaceAgentV2] HostManager thread started")

        # Run event loop
        self._event_loop()

        print("[InterfaceAgentV2] Application terminated")

    def _event_loop(self):
        """
        Main GUI event loop (blocking).

        Handles user input events and processes messages from HostManager.
        """
        print("[InterfaceAgentV2] Entering event loop")

        while True:
            # Read with 100ms timeout
            event, values = self.window.read(timeout=100)

            # Process GUI events
            if event in (sg.WIN_CLOSED, "Exit"):
                print("[InterfaceAgentV2] Window close event")
                break

            elif event == "-SUBMIT-":
                self._handle_prompt_submit(values["-PROMPT-INPUT-"])

            elif event == "-ROLL-":
                self._handle_roll()

            elif event == "-CANCEL-":
                self._handle_cancel()
            
            
            self.window["-PHRASE-"].update(self.host_manager.blackboard.read_single("workflow.current_step"))
            
            # Process messages from HostManager
            self._process_gui_queue()
            self._update_character_display()
            self._update_npc_display()
        
            # Check shutdown
            if self.shutdown_event.is_set():
                break

        # Clean shutdown
        self._shutdown()

    def _handle_prompt_submit(self, prompt_text: str):
        """Handle Submit button click."""
        if not prompt_text or not prompt_text.strip():
            sg.popup_error("Please enter an action", title="Empty Prompt")
            return

        if self.state.flow_running:
            sg.popup_error("Please wait for current action to complete", title="Busy")
            return

        # Update status
        self.window["-STATUS-"].update("Processing action...")

        # Disable input
        self.window["-SUBMIT-"].update(disabled=True)
        self.window["-PROMPT-INPUT-"].update(disabled=True)

        # Set running flag
        self.state.flow_running = True

        # Add prompt to conversation
        self._append_chat(f"\n\n[YOU] {prompt_text}\n")

        # Send to HostManager
        self.host_manager.handle_user_prompt(prompt_text)

        # Clear input
        self.window["-PROMPT-INPUT-"].update("")

    def _handle_roll(self):
        """Handle Roll d20 button click."""
        if not self.state.awaiting_roll:
            return

        # Perform roll
        roll = randint(1, 20)

        # Display result
        dc = self.state.current_difficulty
        success = roll >= dc
        result_text = f"Rolled: {roll} vs DC {dc} - {'SUCCESS!' if success else 'FAILED'}"
        self.window["-ROLL-RESULT-"].update(result_text)

        # Disable roll button
        self.window["-ROLL-"].update(disabled=True)
        self.window["-CANCEL-"].update(disabled=True)

        # Update status
        self.window["-STATUS-"].update("Resolving action...")

        # Clear awaiting flag
        self.state.awaiting_roll = False

        # Send roll to HostManager
        self.host_manager.handle_roll_result(roll)

    def _handle_cancel(self):
        """Handle Cancel button click."""
        if not self.state.awaiting_roll:
            return

        # Hide check panel
        self.window["-CHECK-FRAME-"].update(visible=False)
        self.window["-ROLL-"].update(visible=False)
        self.window["-CANCEL-"].update(visible=False)
        self.window["-ROLL-RESULT-"].update("")

        # Re-enable input
        self.window["-SUBMIT-"].update(disabled=False)
        self.window["-PROMPT-INPUT-"].update(disabled=False)
        self.window["-STATUS-"].update("Action cancelled. Ready for new action.")

        # Clear flags
        self.state.awaiting_roll = False
        self.state.flow_running = False

        # Notify HostManager
        self.host_manager.handle_cancel()

    def _process_gui_queue(self):
        """Process messages from HostManager."""
        while True:
            try:
                msg = self.gui_queue.get_nowait()
                self._handle_message(msg)
            except queue.Empty:
                break

    def _handle_message(self, msg: Message):
        """
        Process a message from HostManager.

        Args:
            msg: Message object
        """
        msg_type = msg.type
        msg_data = msg.data or {}
        
        self._update_character_display()
        self._update_npc_display()
        
        print(f"[InterfaceAgentV2] Received: {msg_type}")

        if msg_type == MessageType.VALIDATION_ERROR:
            # Invalid prompt
            validation_msg = msg_data.get("message", "Invalid action")
            self._append_chat(f"\n\n[SYSTEM] {validation_msg}\n")

            # Re-enable input
            self._reset_input_state()

        elif msg_type == MessageType.ACTION_INFEASIBLE:
            # Action not feasible
            infeasibility_msg = msg_data.get("message", "Action not feasible")
            self._append_chat(f"\n\n[SYSTEM] {infeasibility_msg}\n")

            # Re-enable input
            self._reset_input_state()

        elif msg_type == MessageType.REQUEST_DIFFICULTY_CHECK:
            # Show difficulty check UI
            dc = msg_data.get("difficulty", 10)
            reasoning = msg_data.get("reasoning", "")

            self.state.current_difficulty = dc
            self.state.awaiting_roll = True

            # Update UI
            dc_text = f"Difficulty Check: DC {dc}"
            if reasoning:
                dc_text += f"\n{reasoning[:100]}..."
            self.window["-DC-TEXT-"].update(dc_text)
            self.window["-CHECK-FRAME-"].update(visible=True)
            self.window["-ROLL-"].update(visible=True, disabled=False)
            self.window["-CANCEL-"].update(visible=True)
            self.window["-ROLL-RESULT-"].update("")
            self.window["-STATUS-"].update("Roll d20 to attempt action")

        elif msg_type == MessageType.DISPLAY_NARRATIVE:
            # Display narrative
            narratives = msg_data.get("narratives", {})

            # Display MC narrative
            for speaker, narrative in narratives.items():
                if narrative:
                    self._append_chat(f"\n\n[NARRATOR - {speaker}]\n\n\n{narrative}\n")

            # Update game state from HostManager
            context = self.host_manager.get_game_context_summary()
            self.state.player_hp = context.get("player_hp", self.state.player_hp)
            self.state.current_stage = context.get("current_stage", self.state.current_stage)
            self.state.current_venue = context.get("current_venue", self.state.current_venue)

            # Update displays

            # Hide check panel and re-enable input
            self.window["-CHECK-FRAME-"].update(visible=False)
            self._reset_input_state()

        elif msg_type == MessageType.FLOW_ERROR:
            # Error occurred
            error_msg = msg_data.get("error", "Unknown error")
            self._append_chat(f"[ERROR] {error_msg}\n")

            sg.popup_error(
                f"An error occurred:\n\n{error_msg}",
                title="Error"
            )

            # Reset UI
            self.window["-CHECK-FRAME-"].update(visible=False)
            self._reset_input_state()

    def _reset_input_state(self):
        """Reset input controls to ready state."""
        self.window["-SUBMIT-"].update(disabled=False)
        self.window["-PROMPT-INPUT-"].update(disabled=False)
        self.window["-STATUS-"].update("Ready for action")
        self.state.flow_running = False
        self.state.awaiting_roll = False

    def _append_chat(self, text: str):
        """Append text to chat window."""
        current = self.window["-CHAT-"].get()
        self.window["-CHAT-"].update(current + text + "\n")

    def _update_character_display(self):
        """Update character info display."""
        if not self.host_manager:
            return

        bb = self.host_manager.blackboard
        mc_name = bb.read_single("game_context.main_character_name")
        stage_name = bb.read_single("game_context.current_stage_name")
        venue_name = bb.read_single("game_context.current_venue_name")

        # Get main character data
        mc_data = bb.get_character_data(mc_name) or {}

        # Update main character display
        # Character.to_dict() uses 'hp' and 'max_hp' fields
        mc_hp = mc_data.get("hp", 0)
        mc_max_hp = mc_data.get("max_hp", 0)

        self.window["-PC-NAME-"].update(f"Name: {mc_name}")
        self.window["-PC-HP-"].update(f"HP: {mc_hp}/{mc_max_hp}")
        self.window["-PC-Class-"].update(f"Class: {mc_data.get('character_class', 'Unknown')}")
        self.window["-PC-Level-"].update(f"Level: {mc_data.get('level', 1)}")
        self.window["-PC-STAGE-"].update(f"Stage: {stage_name}")
        self.window["-PC-VENUE-"].update(f"Location: {venue_name}")

        # Update companion displays
        companion_names = bb.read_single("game_context.companion_names") or ["Kael Windrider", "Thora Mossborn"]
        all_characters = bb.read_single("game_context.all_characters") or {}

        for idx, companion_name in enumerate(companion_names):
            if idx >= 2:  # We only have 2 companion slots
                break

            companion_data = all_characters.get(companion_name, {})
            tab_idx = idx + 1  # PC1, PC2

            # Character.to_dict() uses 'hp' and 'max_hp' fields
            companion_hp = companion_data.get("hp", 0)
            companion_max_hp = companion_data.get("max_hp", 0)

            self.window[f"-PC{tab_idx}-NAME-"].update(f"Name: {companion_name}")
            self.window[f"-PC{tab_idx}-HP-"].update(f"HP: {companion_hp}/{companion_max_hp}")
            self.window[f"-PC{tab_idx}-Class-"].update(f"Class: {companion_data.get('character_class', 'Unknown')}")
            self.window[f"-PC{tab_idx}-Level-"].update(f"Level: {companion_data.get('level', 1)}")
            self.window[f"-PC{tab_idx}-STAGE-"].update(f"Stage: {stage_name}")
            self.window[f"-PC{tab_idx}-VENUE-"].update(f"Location: {venue_name}")
            
            

    def _update_npc_display(self):
        """Update NPC status display from blackboard."""
        if not self.host_manager:
            return

        # Get active NPCs from venue data
        bb = self.host_manager.blackboard
        venue_data = bb.get_current_venue_data() or {}
        npc_names_in_venue = venue_data.get("NPCs", [])

        # Try to get active NPC names from current turn, otherwise use all NPCs in venue
        active_npc_names = bb.read_single("current_turn.active_npc_names")
        if not active_npc_names:
            active_npc_names = npc_names_in_venue

        if not active_npc_names:
            self.window["-NPC-STATUS-"].update("No NPCs nearby")
            return

        npc_text = ""
        for npc_name in active_npc_names:
            npc_data = bb.get_npc_data(npc_name)
            if not npc_data:
                # Try companion list
                npc_data = bb.get_character_data(npc_name)

            if npc_data:
                # Character.to_dict() uses 'hp' and 'max_hp' fields
                # But NPC data from campaign might use 'hit_points'
                hp = npc_data.get("hp", npc_data.get("current_hit_points", npc_data.get("hit_points", "?")))
                max_hp = npc_data.get("max_hp", npc_data.get("hit_points", "?"))
                npc_type = npc_data.get("character_class", npc_data.get("type", "NPC"))
                npc_text += f"{'=' * 23}\n"
                npc_text += f"{npc_name} ({npc_type})\n"
                npc_text += f"HP: {hp}/{max_hp}\n"
                npc_text += "\n"

        self.window["-NPC-STATUS-"].update(npc_text.strip() if npc_text else "No NPCs nearby")

    def _shutdown(self):
        """Clean shutdown sequence."""
        print("[InterfaceAgentV2] Initiating shutdown")

        # Signal shutdown
        self.shutdown_event.set()

        # Shutdown HostManager
        if self.host_manager:
            self.host_manager.shutdown()

        # Wait for thread
        if self.host_thread and self.host_thread.is_alive():
            print("[InterfaceAgentV2] Waiting for HostManager thread...")
            self.host_thread.join(timeout=5.0)

        # Close window
        if self.window:
            self.window.close()
            print("[InterfaceAgentV2] Window closed")


def main():
    """Main entry point for Interface Agent V2."""
    print("=" * 60)
    print("D&D Multi-Agent System - Interface Agent V2")
    print("Message-Passing Architecture with Blackboard Pattern")
    print("=" * 60)

    agent = InterfaceAgentV2()
    agent.start()


if __name__ == "__main__":
    main()