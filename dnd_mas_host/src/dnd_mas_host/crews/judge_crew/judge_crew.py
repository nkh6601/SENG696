import yaml
import os
from pathlib import Path
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from crewai import Agent, Task, LLM
from crewai.flow.flow import Flow, listen, start, router


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
    # Inputs
    campaign: str = ""
    player: str = ""
    action: Dict[str, Any] = Field(default_factory=dict)
    roll: int = 0

    # Phase tracking
    workflow_phase: str = ""  # "difficulty_assessment" or "consequence_evaluation"

    # Outputs
    feasibility_result: Optional[Dict[str, Any]] = None
    difficulty: int = 10
    difficulty_reasoning: str = ""
    skip_difficulty_check: bool = False
    effect: str = ""
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

    def _load_agent_config(self, agent_name: str) -> Agent:
        """Load agent configuration from agents.yaml"""
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

        return Agent(
            role=config['role'],
            goal=config['goal'],
            backstory=config['backstory'],
            llm=LLM(model=model),
            verbose=True,
            allow_delegation=False
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
        """Determine workflow phase based on inputs"""
        # Phase 1: Difficulty Assessment - roll == 0
        if self.state.roll == 0:
            self.state.workflow_phase = "difficulty_assessment"
        # Phase 2: Consequence Evaluation - roll > 0
        else:
            self.state.workflow_phase = "consequence_evaluation"

        return self.state

    @router(determine_phase)
    def route_phase(self):
        """Route to appropriate workflow phase"""
        if self.state.workflow_phase == "difficulty_assessment":
            return "assess_difficulty"
        else:
            return "evaluate_consequences"

    @listen("assess_difficulty")
    def check_feasibility_step(self):
        """Check if action is feasible under D&D 5E rules"""
        # Load agent and task from YAML
        agent = self._load_agent_config("feasibility_agent")
        task = self._load_task_config("check_feasibility", agent, FeasibilityOutput)

        # Execute task
        result = self._execute_task_sync(task, {
            "campaign": self.state.campaign,
            "player": self.state.player,
            "action": str(self.state.action)
        })

        # Update state
        self.state.feasibility_result = result.dict()

        return self.state

    @router(check_feasibility_step)
    def route_feasibility(self):
        """Route based on feasibility result"""
        if self.state.feasibility_result and self.state.feasibility_result.get("is_valid"):
            return "do_assign_difficulty"  # Different from listener function name
        else:
            return "do_feasibility_failed"  # Different from listener function name

    @listen("do_feasibility_failed")
    def feasibility_failed(self):
        """Terminal state for infeasible actions (TERMINAL)"""
        # State already contains feasibility_result with rejection_message
        print("[JudgeFlow] Action infeasible - TERMINAL")
        return self.state

    @listen("do_assign_difficulty")
    def assign_difficulty_step(self):
        """Assign difficulty class for the action (TERMINAL)"""
        # Load agent and task from YAML
        agent = self._load_agent_config("difficulty_agent")
        task = self._load_task_config("assign_difficulty", agent, DifficultyOutput)

        # Execute task
        result = self._execute_task_sync(task, {
            "campaign": self.state.campaign,
            "player": self.state.player,
            "action": str(self.state.action)
        })

        # Update state
        self.state.difficulty = result.difficulty
        self.state.difficulty_reasoning = result.reasoning
        self.state.skip_difficulty_check = result.skip_check

        # TERMINAL: No further routing, flow ends here
        print("[JudgeFlow] Difficulty assessment complete - TERMINAL")
        return self.state

    @listen("evaluate_consequences")
    def evaluate_consequences_step(self):
        """Evaluate consequences of action success/failure (TERMINAL)"""
        # Load agent and task from YAML
        agent = self._load_agent_config("consequence_agent")
        task = self._load_task_config("evaluate_consequence", agent, ConsequenceOutput)

        # Execute task with roll result
        result = self._execute_task_sync(task, {
            "campaign": self.state.campaign,
            "player": self.state.player,
            "action": str(self.state.action),
            "roll": str(self.state.roll)
        })

        # Update state
        self.state.effect = result.effect
        self.state.effect_reasoning = result.reasoning
        self.state.time_used = result.time_used

        # TERMINAL: No further routing, flow ends here
        print("[JudgeFlow] Consequence evaluation complete - TERMINAL")
        return self.state
