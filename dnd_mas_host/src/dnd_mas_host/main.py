#!/usr/bin/env python
from random import randint
from typing import List, Dict, Optional, Any
from enum import Enum
import queue

from pydantic import BaseModel, Field

from crewai.flow.flow import Flow, listen, start, router

from dnd_mas_host.crews.judge_crew.judge_crew import JudgeCrew

from dnd_mas_host.crews.narrator_crew.narrator_crew import NarratorCrew

from dnd_mas_host.crews.npc_crew.npc_crew import NpcCrew


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
    State model for D&D MAS workflow coordination.

    This tracks workflow state across all crews. Note that the Narrator Agent
    also maintains internal memory (story progress, combat state, etc.) that
    is NOT stored in HostState.
    """
    # Workflow
    workflow_step: WorkflowStep = Field(default=WorkflowStep.STEP_1_RECEIVE_PROMPT, description="Current step in the game loop")
    current_agent: str = Field(default="", description="Name of the agent currently processing")
    flow_complete: bool = Field(default=False, description="Flag to indicate flow completion (for debugging)")

    # Campaign and Player
    campaign: str = Field(default="Humantown", description="Campaign name")
    player: str = Field(default="Adventurer", description="Player character name")
    player_class: str = Field(default="Fighter", description="Player character class")
    player_background: str = Field(default="", description="Player character background")

    # User interaction
    prompt_text: str = Field(default="", description="Current user's prompt being processed")
    prompt_valid: bool = Field(default=True, description="Whether the prompt passed validation")
    validation_message: Optional[str] = Field(default=None, description="Validation feedback message if prompt is invalid")

    # Action processing
    action_extracted: Optional[Dict[str, Any]] = Field(default=None, description="Extracted action (action_type, target, method, intent)")
    Action_difficulty: Dict[str, int] = Field(default_factory=dict, description="Action difficulty assigned by Judge Agent")
    difficulty_check: int = Field(default=0, description="The d20 roll result for difficulty check")
    skip_difficulty_check: bool = Field(default=False, description="Whether to skip difficulty check (too easy/impossible)")
    effect: Optional[str] = Field(default=None, description="The effect of action evaluated by Judge Agent")

    # NPC tracking (retrieved from MongoDB when needed based on venue/stage)
    active_npcs: List[Dict[str, Any]] = Field(default_factory=list, description="NPCs in current venue (retrieved from MongoDB)")
    npc_reactions_completed: List[Dict[str, Any]] = Field(default_factory=list, description="List of completed NPC reactions with narratives")

    # Output
    final_output: str = Field(default="", description="Final generated narrative to display to user")

    # Game state (MVP - minimal fields, Narrator Agent tracks more in internal memory)
    current_stage: str = Field(default="", description="Current story stage")
    current_venue: str = Field(default="", description="Current location/venue")
    character_hp: int = Field(default=20, description="Main character current HP")
    character_max_hp: int = Field(default=20, description="Main character maximum HP")



class HostFlow(Flow[HostState]):
    """
    D&D MAS 12-step game loop orchestration using CrewAI Flow.

    This flow coordinates 3 crews (Narrator, Judge, NPC) through the complete
    game loop with conditional branching based on validation and difficulty checks.
    """

    def __init__(self, gui_queues: Optional[Dict[str, queue.Queue]] = None):
        """
        Initialize HostFlow with optional GUI communication queues.

        Args:
            gui_queues: Optional dict with 'to_flow' and 'from_flow' queues for GUI integration
        """
        super().__init__()
        self.gui_queues = gui_queues

    @start()
    def receive_prompt(self):
        """Step 1: Interface receives user input"""
        self.state.workflow_step = WorkflowStep.STEP_1_RECEIVE_PROMPT
        self.state.current_agent = "Interface"
        # self.state.prompt_text should be set before kickoff
        return self.state

    @listen(receive_prompt)
    def validate_and_extract(self):
        """Steps 2-3: Narrator validates + extracts (all 3 tasks execute)"""
        self.state.workflow_step = WorkflowStep.STEP_2_VALIDATE_PROMPT
        self.state.current_agent = "Narrator"

        result = NarratorCrew().crew().kickoff(
            inputs={
                "campaign": self.state.campaign,
                "player": self.state.player,
                "prompt": self.state.prompt_text,
                "current_venue": self.state.current_venue
            }
        )

        # All 3 tasks executed - extract outputs from task_outputs
        # Task 0: validate_prompt
        try:
            validation_output = result.tasks_output[0].to_dict()
            self.state.prompt_valid = validation_output.get("valid", True)
            self.state.validation_message = validation_output.get("message", "")
        except Exception as e:
            print(f"Error parsing validation output: {e}")
            self.state.prompt_valid = True  # Default to valid on parse error
            self.state.validation_message = ""

        # Task 1: action_extract (only if validation passed)
        if self.state.prompt_valid and len(result.tasks_output) > 1:
            try:
                self.state.action_extracted = result.tasks_output[1].to_dict()
            except Exception as e:
                print(f"Error parsing action extraction output: {e}")
                self.state.action_extracted = {"action": "unknown"}

        # Task 2: narrative_task (skipped - no action/effect/reactions yet)
        return self.state

    @router(validate_and_extract)
    def route_validation(self):
        """Route based on prompt validation"""
        if self.state.prompt_valid:
            return "check_difficulty"
        else:
            return "request_clarification"

    @listen("request_clarification")
    def request_clarification(self):
        """Exception: Invalid prompt"""
        self.state.workflow_step = WorkflowStep.EXCEPTION_INVALID_PROMPT
        self.state.current_agent = "Interface"
        self.state.final_output = self.state.validation_message or "Invalid prompt. Please clarify."

        # Send validation error to GUI if available
        if self.gui_queues:
            from dnd_mas_host.interface.message_types import MessageType, create_message

            self.gui_queues["from_flow"].put(create_message(
                MessageType.VALIDATION_ERROR,
                {"message": self.state.validation_message or "Invalid prompt. Please clarify."}
            ))

        return self.state

    @listen("check_difficulty")
    def evaluate_difficulty(self):
        """Step 4: Judge evaluates difficulty"""
        self.state.workflow_step = WorkflowStep.STEP_4_EVALUATE_DIFFICULTY
        self.state.current_agent = "Judge"

        result = JudgeCrew().crew().kickoff(
            inputs={
                "campaign": self.state.campaign,
                "player": self.state.player,
                "action": self.state.action_extracted
            }
        )

        # Judge has 2 tasks - get first task output (difficulty)
        try:
            difficulty_output = result.tasks_output[0].to_dict()
            self.state.Action_difficulty = difficulty_output
            self.state.skip_difficulty_check = difficulty_output.get("skip_check", False)
        except Exception as e:
            print(f"Error parsing difficulty output: {e}")
            self.state.Action_difficulty = {"difficulty": 10}
            self.state.skip_difficulty_check = False

        return self.state

    @router(evaluate_difficulty)
    def route_difficulty(self):
        """Route based on difficulty check requirement"""
        if self.state.skip_difficulty_check:
            return "skip_to_consequences"
        else:
            return "perform_check"

    @listen("perform_check")
    def perform_check(self):
        """Step 5: Interface performs d20 roll (via GUI if available)"""
        self.state.workflow_step = WorkflowStep.STEP_5_PERFORM_CHECK
        self.state.current_agent = "Interface"

        if self.gui_queues:
            # GUI mode: Request roll from user
            from dnd_mas_host.interface.message_types import MessageType, create_message

            self.gui_queues["from_flow"].put(create_message(
                MessageType.REQUEST_DIFFICULTY_CHECK,
                {
                    "action": self.state.action_extracted.get("action", "Unknown action") if self.state.action_extracted else "Unknown action",
                    "dc": self.state.Action_difficulty.get("difficulty", 10),
                    "skip_check": self.state.skip_difficulty_check
                }
            ))

            # Block until user responds
            while True:
                try:
                    msg = self.gui_queues["to_flow"].get(timeout=1.0)
                    msg_type = msg.get("type")

                    if msg_type == MessageType.ROLL_D20:
                        self.state.difficulty_check = msg["data"]["roll"]
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
    def evaluate_consequences(self):
        """Step 6: Judge evaluates consequences"""
        self.state.workflow_step = WorkflowStep.STEP_6_EVALUATE_CONSEQUENCES
        self.state.current_agent = "Judge"

        result = JudgeCrew().crew().kickoff(
            inputs={
                "campaign": self.state.campaign,
                "player": self.state.player,
                "action": self.state.action_extracted,
                "roll": self.state.difficulty_check,
                "difficulty": self.state.Action_difficulty
            }
        )

        # Get second task output (consequences)
        try:
            if len(result.tasks_output) > 1:
                consequences_output = result.tasks_output[1].to_dict()
            else:
                consequences_output = {}

            self.state.effect = consequences_output.get("effect", "No effect")
        except Exception as e:
            print(f"Error parsing consequences output: {e}")
            self.state.effect = "Unknown effect"

        return self.state

    @listen(evaluate_consequences)
    def process_npc_reactions(self):
        """Steps 7-9: NPC reactions - Each NPC gets own crew instance"""
        self.state.workflow_step = WorkflowStep.STEP_7_EVALUATE_NPC_REACTIONS
        self.state.current_agent = "NPC"

        # TODO: Retrieve NPCs from MongoDB based on current_venue
        # For now, using empty list if no NPCs loaded
        # Future: Query venues collection to get NPCs present in current venue
        # Then query npcs collection for each NPC's full details

        if not self.state.active_npcs:
            # No NPCs in venue, skip NPC reactions
            self.state.npc_reactions_completed = []
            return self.state

        # Process each NPC with separate crew instance
        # This allows each NPC to maintain independent state and react independently
        all_reactions = []

        for npc in self.state.active_npcs:
            # Create separate NPC crew for this specific NPC
            npc_crew = NpcCrew().crew()

            result = npc_crew.kickoff(
                inputs={
                    "campaign": self.state.campaign,
                    "player": self.state.player,
                    "NPC_role": npc.get("name", "Unknown NPC"),
                    "NPC_goal": npc.get("intention", ""),
                    "NPC_background": npc.get("desc", ""),
                    "action": self.state.action_extracted,
                    "effect": self.state.effect,
                    "venue": self.state.current_venue
                }
            )

            # Extract reaction from this NPC's crew
            try:
                # Get last task output (evaluate_reaction)
                if len(result.tasks_output) > 0:
                    reactions_output = result.tasks_output[-1].to_dict()
                    npc_reaction = reactions_output.get("reaction", "")

                    # Add NPC identifier to track which NPC reacted
                    if npc_reaction:
                        all_reactions.append({
                            "npc_name": npc.get("name", "Unknown NPC"),
                            "reaction": npc_reaction,
                            "reasoning": reactions_output.get("reasoning", "")
                        })
            except Exception as e:
                print(f"Error parsing NPC reaction for {npc.get('name', 'Unknown')}: {e}")

        self.state.npc_reactions_completed = all_reactions
        return self.state

    @listen(process_npc_reactions)
    def generate_narrative(self):
        """Step 10: Narrator generates narrative (all 3 tasks execute again)"""
        self.state.workflow_step = WorkflowStep.STEP_10_GENERATE_NARRATIVE
        self.state.current_agent = "Narrator"

        result = NarratorCrew().crew().kickoff(
            inputs={
                "campaign": self.state.campaign,
                "player": self.state.player,
                "prompt": "",  # Empty - validation skips
                "action": self.state.action_extracted,
                "effect": self.state.effect,
                "reactions": self.state.npc_reactions_completed,
                "current_venue": self.state.current_venue
            }
        )

        # All 3 tasks executed - get narrative from task 0 (narrative_task is first in the task list)
        try:
            if len(result.tasks_output) > 0:
                narrative_output = result.tasks_output[0].to_dict()
            else:
                narrative_output = {}

            self.state.final_output = narrative_output.get("narrative", "No narrative generated")

            # Update game state from narrator
            state_updates = narrative_output.get("state_updates", {})
            self.state.character_hp = state_updates.get("character_hp", self.state.character_hp)
            self.state.current_venue = state_updates.get("current_venue", self.state.current_venue)
        except Exception as e:
            print(f"Error parsing narrative output: {e}")
            self.state.final_output = "Error generating narrative"

        return self.state

    @listen(generate_narrative)
    def display_output(self):
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


if __name__ == "__main__":
    kickoff()
