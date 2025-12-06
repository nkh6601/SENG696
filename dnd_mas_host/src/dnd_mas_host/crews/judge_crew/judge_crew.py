import yaml
import os
from pathlib import Path
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from crewai import Agent, Task, LLM
from crewai.flow.flow import Flow, listen, start, router

from dnd_mas_host.interface.message_types import Message, MessageType, create_message
from dnd_mas_host.state.host_state import Action, ActionType, WorkflowStep, Consequence, ConsequenceType


# Output models for structured task outputs
class FeasibilityOutput(BaseModel):
    """Output model for feasibility check task"""
    is_valid: bool = Field(description="Whether the action is valid according to D&D 5E rules")
    reasoning: str = Field(description="Reasoning about why the action is valid or invalid")
    rejection_message: Optional[str] = Field(default=None, description="User-friendly message if action is invalid")


class DifficultyOutput(BaseModel):
    """Output model for difficulty assignment task"""
    difficulty: int = Field(description="Difficulty level from -1 to 21")
    reasoning: str = Field(description="Reasoning about the difficulty")
    skip_check: bool = Field(default=False, description="Whether to skip difficulty check (-1 or 21)")


class ConsequenceOutput(BaseModel):
    """Output model for consequence evaluation task"""
    effect: str = Field(description="Description of the action's impact")
    reasoning: str = Field(description="Reasoning about the consequences")
    time_used: Optional[str] = Field(default=None, description="Time the action took")


# Flow State Model
class JudgeState(BaseModel):
    """State model for JudgeFlow"""
    msg: Optional[Message] = None

    # Phase tracking
    workflow_phase: str = ""  # "difficulty_assessment" or "consequence_evaluation"

    # Outputs
    feasibility_result: Optional[Dict[str, Any]] = None
    difficulty: int = 10
    difficulty_reasoning: str = ""
    skip_difficulty_check: bool = False
    effect: str = ""
    effect_type: str = ""
    effect_reasoning: str = ""
    time_used: Optional[str] = None


class JudgeFlow(Flow[JudgeState]):
    """
    Flow-based Judge crew for D&D MAS.

    Handles two workflow phases:
    1. Difficulty Assessment Phase: feasibility → difficulty
    2. Consequence Evaluation Phase: evaluate consequences

    Uses explicit Flow routing instead of hierarchical manager delegation.
    """

    def __init__(self):
        super().__init__()
        self.config_dir = Path(__file__).parent / "config"
        self.tools = self._create_tools()
        self.host_manager = None
        self.bb = None

    def _create_tools(self) -> dict:
        """
        Create tools for each Judge agent based on Tool Assignment Matrix.

        Returns a dict mapping agent names to their specific tool lists.
        """
        from dnd_mas_host.tools.mongodb_vector_tools import (
            # VenueVectorSearchTool,       # DISABLED - use passed state
            MonsterVectorSearchTool,
            SpellVectorSearchTool,
            RuleVectorSearchTool,
            ClassVectorSearchTool,
            ConditionVectorSearchTool
        )

        return {
            # Feasibility Agent: Validate action legality
            "feasibility_agent": [
                RuleVectorSearchTool(),        # D&D 5E rules
                SpellVectorSearchTool(),       # Spell components/requirements
                ClassVectorSearchTool(),       # Class features/abilities
            ],

            # Difficulty Agent: Assign DC
            "difficulty_agent": [
                MonsterVectorSearchTool(),     # Enemy stats
                RuleVectorSearchTool(),        # Official DC guidelines
                ConditionVectorSearchTool(),   # Status effect impacts
                # REMOVED: VenueVectorSearchTool - use passed current_venue_obj
            ],

            # Consequence Agent: Determine effects
            "consequence_agent": [
                MonsterVectorSearchTool(),     # Damage calculations
                SpellVectorSearchTool(),       # Spell effects
                ConditionVectorSearchTool(),   # Status conditions
                RuleVectorSearchTool(),        # Mechanical rules
            ]
        }

    def _load_agent_config(self, agent_name: str, tools: list) -> Agent:
        """
        Load agent configuration from agents.yaml with specific tools.

        Args:
            agent_name: Name of the agent to load
            tools: List of tools to assign to this agent
        """
        agents_file = self.config_dir / "agents.yaml"
        with open(agents_file, 'r') as f:
            agents_config = yaml.safe_load(f)

        if agent_name not in agents_config:
            raise ValueError(f"Agent '{agent_name}' not found in agents.yaml")

        config = agents_config[agent_name]

        # Get LLM from environment
        from dotenv import load_dotenv
        load_dotenv()
        model = os.getenv("MODEL", "gpt-4o-mini")

        # Import execution control settings
        from dnd_mas_host.config import MAX_ITER, MAX_EXECUTION_TIME, MAX_RPM, MAX_RETRY_LIMIT

        return Agent(
            role=config['role'],
            goal=config['goal'],
            backstory=config['backstory'],
            llm=LLM(model=model),
            verbose=True,
            allow_delegation=False,
            tools=tools,  # Use agent-specific tools
            max_iter=MAX_ITER,
            max_execution_time=MAX_EXECUTION_TIME,
            max_rpm=MAX_RPM,
            max_retry_limit=MAX_RETRY_LIMIT
        )

    def _load_task_config(self, task_name: str, agent: Agent, output_model: BaseModel) -> Task:
        """Load task configuration from tasks.yaml"""
        tasks_file = self.config_dir / "tasks.yaml"
        with open(tasks_file, 'r') as f:
            tasks_config = yaml.safe_load(f)

        if task_name not in tasks_config:
            raise ValueError(f"Task '{task_name}' not found in tasks.yaml")

        config = tasks_config[task_name]

        return Task(
            description=config['description'],
            expected_output=config['expected_output'],
            agent=agent,
            output_pydantic=output_model
        )

    def _execute_task_sync(self, task: Task, inputs: Dict) -> Any:
        """Execute task synchronously and return parsed output"""
        # Format task description with inputs
        formatted_description = task.description
        for key, value in inputs.items():
            formatted_description = formatted_description.replace(f"{{{key}}}", str(value))

        task.description = formatted_description

        # Execute task
        result = task.execute_sync()

        # Return pydantic model if available
        if result.pydantic:
            return result.pydantic
        else:
            raise ValueError(f"Task execution failed to produce pydantic output: {result.raw}")

    @start()
    def determine_phase(self):
        """Determine workflow phase based on message type"""
        if not self.state.msg:
            raise ValueError("No message provided to JudgeFlow")

        # Phase 1: Difficulty Assessment - CHECK_FEASIBILITY
        if self.state.msg.type == MessageType.CHECK_FEASIBILITY:
            self.state.workflow_phase = "difficulty_assessment"
            print(f"[DEBUG] Workflow phase set to: difficulty_assessment")
        # Phase 2: Consequence Evaluation - EVALUATE_CONSEQUENCE or EVALUATE_NPC_CONSEQUENCE
        elif self.state.msg.type in [MessageType.EVALUATE_CONSEQUENCE, MessageType.EVALUATE_NPC_CONSEQUENCE]:
            self.state.workflow_phase = "consequence_evaluation"
            print(f"[DEBUG] Workflow phase set to: consequence_evaluation")
        else:
            raise ValueError(f"Invalid message type for JudgeFlow: {self.state.msg.type}")

        return self.state

    @router(determine_phase)
    def route_phase(self):
        """Route to appropriate workflow phase"""
        print(f"[DEBUG] route_phase: workflow_phase={self.state.workflow_phase}")

        if self.state.workflow_phase == "difficulty_assessment":
            print("[DEBUG] Routing to assess_difficulty")
            return "assess_difficulty"
        else:
            print("[DEBUG] Routing to evaluate_consequences")
            return "evaluate_consequences"

    @listen("assess_difficulty")
    def check_feasibility_step(self):
        """Check if action is feasible under D&D 5E rules"""
        print(f"[DEBUG] JudgeFlow.check_feasibility_step() called")

        bb = self.bb
        state_text = bb.praseState()

        # Load agent and task from YAML
        agent = self._load_agent_config("feasibility_agent", self.tools["feasibility_agent"])
        task = self._load_task_config("check_feasibility", agent, FeasibilityOutput)

        current_turn = bb.read_single("current_turn")
        
        # Execute task
        result = self._execute_task_sync(task, {
            "state_text": state_text,
            "action": str(current_turn.action_extracted)
        })

        # Update state
        self.state.feasibility_result = result.dict()

        print(f"[DEBUG] Feasibility check: is_valid={result.is_valid}")

        return self.state

    @router(check_feasibility_step)
    def route_feasibility(self):
        """Route based on feasibility result"""
        print(f"[DEBUG] route_feasibility() ENTERED: is_valid={self.state.feasibility_result.get('is_valid')}")

        if self.state.feasibility_result and self.state.feasibility_result.get("is_valid"):
            print("[DEBUG] Routing to do_assign_difficulty")
            return "do_assign_difficulty"
        else:
            print("[DEBUG] Feasibility failed - ending flow (no route)")
            # Action infeasible - send error to Interface
            bb = self.bb
            bb.write({"current_turn.skip_difficulty_check": True})
            
            self.host_manager.send_message(create_message(
                to="Interface",
                msg_type=MessageType.ACTION_INFEASIBLE,
                data={"message": self.state.feasibility_result.get("rejection_message", "Action not feasible")},
                from_agent="Judge"
            ))
            return None

    @listen("do_assign_difficulty")
    def assign_difficulty_step(self):
        """Assign difficulty class for the action"""
        print(f"[DEBUG] JudgeFlow.assign_difficulty_step() called")

        bb = self.bb
        state_text = bb.praseState()

        # Load agent and task from YAML
        agent = self._load_agent_config("difficulty_agent", self.tools["difficulty_agent"])
        task = self._load_task_config("assign_difficulty", agent, DifficultyOutput)
        
        current_turn = bb.read_single("current_turn")
        
        # Execute task
        result = self._execute_task_sync(task, {
            "state_text": state_text,
            "action": str(current_turn.action_extracted)
        })

        # Update state
        self.state.difficulty = result.difficulty
        self.state.difficulty_reasoning = result.reasoning
        self.state.skip_difficulty_check = result.skip_check

        print(f"[DEBUG] Difficulty assigned: DC={result.difficulty}, skip_check={result.skip_check}")

        # Update action with difficulty in blackboard
        action = bb.read_single("current_turn.action_extracted")
        if action:
            action.difficulty = result.difficulty
            bb.write({"current_turn.action_extracted": action})

        # Check if skip difficulty check
        if result.skip_check or result.difficulty == -1 or result.difficulty >= 21:
            bb.write({"current_turn.skip_difficulty_check": True})

            if result.difficulty == -1:
                # Auto-fail
                bb.write({"current_turn.difficulty_check": 0})
                self.host_manager.send_message(create_message(
                    to="Judge",
                    msg_type=MessageType.EVALUATE_CONSEQUENCE,
                    from_agent="Judge"
                ))
            else:
                # Auto-success (DC 21+ is trivial)
                bb.write({"current_turn.difficulty_check": 21})
                self.host_manager.send_message(create_message(
                    to="Judge",
                    msg_type=MessageType.EVALUATE_CONSEQUENCE,
                    from_agent="Judge"
                ))
        else:
            # Need user to roll
            bb.write({"workflow.current_step": WorkflowStep.STEP_4_REQUEST_ROLL})
            self.host_manager.send_message(create_message(
                to="Interface",
                msg_type=MessageType.REQUEST_DIFFICULTY_CHECK,
                data={
                    "difficulty": result.difficulty,
                    "reasoning": result.reasoning
                },
                from_agent="Judge"
            ))

        return self.state

    @listen("evaluate_consequences")
    def evaluate_consequences_step(self):
        """Evaluate consequences of action success/failure"""
        print(f"[DEBUG] JudgeFlow.evaluate_consequences_step() called")

        bb = self.bb

        # For NPC consequence evaluation, temporarily write NPC data to blackboard
        if self.state.msg.type == MessageType.EVALUATE_NPC_CONSEQUENCE:
            npc_data = self.state.msg.data
            # Temporarily store NPC action and roll
            bb.write({
                "current_turn.npc_temp_action": npc_data.get("action"),
                "current_turn.npc_temp_roll": npc_data.get("roll", 10),
                "current_turn.npc_temp_name": npc_data.get("npc_name")
            })

        state_text = bb.praseState()

        current_turn = bb.read_single("current_turn")
        # Load agent and task from YAML
        agent = self._load_agent_config("consequence_agent", self.tools["consequence_agent"])
        task = self._load_task_config("evaluate_consequence", agent, ConsequenceOutput)

        # Execute task with roll result
        result = self._execute_task_sync(task, {
            "state_text": state_text,
            "action": str(current_turn.action_extracted),
            "roll": str(current_turn.difficulty_check)
        })

        # Update state
        self.state.effect = result.effect
        self.state.effect = result.effect
        self.state.effect_reasoning = result.reasoning
        self.state.time_used = result.time_used

        print(f"[DEBUG] Consequence evaluated: {result.effect[:100]}...")

        # Convert effect string to Consequence list
        if self.state.msg.type == MessageType.EVALUATE_NPC_CONSEQUENCE:
            # For NPC, use temporary action
            action_data = bb.read_single("current_turn.npc_temp_action")
            target = action_data.get("target") if action_data else None
            # Clear temporary data
            bb.write({
                "current_turn.npc_temp_action": None,
                "current_turn.npc_temp_roll": None,
                "current_turn.npc_temp_name": None
            })
        else:
            # Main character consequence
            action = bb.read_single("current_turn.action_extracted")
            target = action.target if action else None

        consequences = self._parse_effect_to_consequences(result.dict(), target)

        # Check if this is for an NPC (from message data)
        if self.state.msg.type == MessageType.EVALUATE_NPC_CONSEQUENCE:
            # Store consequences in state for retrieval by host_manager
            # (not written to blackboard)
            return self.state
        else:
            # Main character consequence
            bb.write({"current_turn.mc_consequence": consequences})

            # Trigger NPC reactions
            bb.write({"workflow.current_step": WorkflowStep.STEP_7_EVALUATE_REACTIONS})
            self.host_manager.send_message(create_message(
                to="NPC",
                msg_type=MessageType.EVALUATE_REACTIONS,
                from_agent="Judge"
            ))

        return self.state

    def _parse_effect_to_consequences(self, effect: dict, target: Optional[str]) -> list:
        """
        Parse effect string to list of Consequence objects.

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
            consequence_type=ConsequenceType(effect.get("effect_type", "environmental")),  # Generic type
            target_name=target or None,
            description=effect.get("effect", ""),
            time_used=effect.get("time_used", "10 second"),
            damage_amount = int(effect.get("damage_amount", 3)),
            damage_type=effect.get("damage_type", "damage_type"),

            # HEALING
            healing_amount = int(effect.get("healing_amount", 3)),

            # MOVEMENT
            new_location = effect.get("new_location", None),

            # STATUS_EFFECT
            status_effect = effect.get("status_effect", ""),
            duration = effect.get("duration", 3),

            # ITEM_CHANGE
            item_gained = effect.get("item_gained", ""),
            item_lost = effect.get("item_lost", ""),

            # NPC_STATE_CHANGE
            npc_state_change= None,
        )]
