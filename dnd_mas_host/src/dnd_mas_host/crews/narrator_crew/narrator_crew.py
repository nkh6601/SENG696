import yaml
import os
from pathlib import Path
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from crewai import Agent, Task, LLM
from crewai.flow.flow import Flow, listen, start, router


# Output models for structured task outputs
class ValidationOutput(BaseModel):
    """Output model for validate_prompt task"""
    valid: bool = Field(description="Whether the prompt is valid")
    message: str = Field(description="Validation message or clarification request")


class ActionExtractionOutput(BaseModel):
    """Output model for action_extract task"""
    action_type: str = Field(description="Type of action")
    target: str = Field(description="Target of the action")
    method: str = Field(description="Method or approach")
    intent: str = Field(description="Player's intent")


class NarrativeOutput(BaseModel):
    """Output model for narrative_task"""
    narrative: str = Field(description="Generated narrative text")
    state_updates: Dict[str, Any] = Field(default_factory=dict, description="Game state updates")


# Flow State Model
class NarratorState(BaseModel):
    """State model for NarratorFlow"""
    # Inputs
    campaign: str = ""
    player: str = ""
    prompt: str = ""
    current_venue: str = ""
    action: Optional[Dict[str, Any]] = None
    effect: Optional[str] = None
    reactions: List[Dict[str, Any]] = Field(default_factory=list)

    # Phase tracking
    workflow_phase: str = ""  # "validation" or "narrative"

    # Outputs
    prompt_valid: bool = True
    validation_message: str = ""
    action_extracted: Optional[Dict[str, Any]] = None
    narrative: str = ""
    state_updates: Dict[str, Any] = Field(default_factory=dict)


class NarratorFlow(Flow[NarratorState]):
    """
    Flow-based Narrator crew for D&D MAS.

    Handles two workflow phases:
    1. Validation Phase: validate_prompt → extract_action
    2. Narrative Generation Phase: generate_narrative

    Uses explicit Flow routing instead of hierarchical manager delegation.
    """

    def __init__(self):
        super().__init__()
        self.config_dir = Path(__file__).parent / "config"
        self.tools = self._create_tools()

    def _create_tools(self) -> list:
        """Create all tools for Narrator agents"""
        from dnd_mas_host.tools.mongodb_vector_tools import (
            NPCVectorSearchTool,
            VenueVectorSearchTool,
            StageVectorSearchTool,
            UniversalVectorSearchTool,
            MonsterVectorSearchTool,
            SpellVectorSearchTool,
            RuleVectorSearchTool,
            EquipmentVectorSearchTool,
            ClassVectorSearchTool,
            ConditionVectorSearchTool,
            MagicItemVectorSearchTool
        )

        return [
            # Campaign tools (primary for Narrator)
            NPCVectorSearchTool(),
            VenueVectorSearchTool(),
            StageVectorSearchTool(),
            UniversalVectorSearchTool(),

            # 5E database tools (secondary, for validation/narrative enrichment)
            MonsterVectorSearchTool(),
            SpellVectorSearchTool(),
            RuleVectorSearchTool(),
            EquipmentVectorSearchTool(),
            ClassVectorSearchTool(),
            ConditionVectorSearchTool(),
            MagicItemVectorSearchTool()
        ]

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
            allow_delegation=False,
            tools=self.tools
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
        print(f"[DEBUG] NarratorFlow.determine_phase() called")
        print(f"[DEBUG]   - prompt: '{self.state.prompt[:50] if self.state.prompt else None}...'")
        print(f"[DEBUG]   - action: {self.state.action}")
        print(f"[DEBUG]   - effect: {self.state.effect}")
        print(f"[DEBUG]   - reactions: {self.state.reactions}")

        # Phase 1: Validation - prompt provided, no action
        if self.state.prompt and not self.state.action:
            self.state.workflow_phase = "validation"
            print(f"[DEBUG] Workflow phase set to: validation")
        # Phase 2: Narrative - action/effect/reactions provided
        elif self.state.action is not None:
            self.state.workflow_phase = "narrative"
            print(f"[DEBUG] Workflow phase set to: narrative")
        else:
            raise ValueError("Invalid inputs: must provide either 'prompt' or 'action'")

        return self.state

    @router(determine_phase)
    def route_phase(self):
        """Route to appropriate workflow phase"""
        print(f"[DEBUG] route_phase: workflow_phase={self.state.workflow_phase}")

        if self.state.workflow_phase == "validation":
            print("[DEBUG] Routing to do_validate_prompt")
            return "do_validate_prompt"
        else:
            print("[DEBUG] Routing to do_generate_narrative")
            return "do_generate_narrative"

    @listen("do_validate_prompt")
    def validate_prompt_step(self):
        """Validate player prompt for conflicts and ambiguities"""
        print(f"[DEBUG] NarratorFlow.validate_prompt_step() called with prompt='{self.state.prompt[:50]}...'")

        # Load agent and task from YAML
        agent = self._load_agent_config("prompt_validator")
        task = self._load_task_config("validate_prompt", agent, ValidationOutput)

        # Execute task
        result = self._execute_task_sync(task, {
            "campaign": self.state.campaign,
            "player": self.state.player,
            "prompt": self.state.prompt,
            "current_venue": self.state.current_venue
        })

        # DEBUG: Log the result
        print(f"[DEBUG] ValidationOutput received:")
        print(f"[DEBUG]   - valid: {result.valid}")
        print(f"[DEBUG]   - message: {result.message[:100]}...")

        # Update state
        self.state.prompt_valid = result.valid
        self.state.validation_message = result.message

        # DEBUG: Log the state
        print(f"[DEBUG] State updated: prompt_valid={self.state.prompt_valid}")

        return self.state

    @router(validate_prompt_step)
    def route_validation(self):
        """Route based on validation result"""
        # DEBUG: Log the routing decision
        print(f"[DEBUG] route_validation() ENTERED: prompt_valid={self.state.prompt_valid}")

        if self.state.prompt_valid:
            print("[DEBUG] Routing to do_extract_action")
            return "do_extract_action"
        else:
            print("[DEBUG] Validation failed - ending flow (no route)")
            # State already contains validation_message from validate_prompt_step
            # Return None to terminate the flow without triggering any more listeners
            return None

    @listen("do_extract_action")
    def extract_action_step(self):
        """Extract structured action from validated prompt"""
        # Load agent and task from YAML
        agent = self._load_agent_config("action_extractor")
        task = self._load_task_config("action_extract", agent, ActionExtractionOutput)

        # Execute task
        result = self._execute_task_sync(task, {
            "campaign": self.state.campaign,
            "player": self.state.player,
            "prompt": self.state.prompt,
            "current_venue": self.state.current_venue
        })

        # Update state
        self.state.action_extracted = result.dict()

        return self.state

    @listen("do_generate_narrative")
    def generate_narrative_step(self):
        """Generate narrative from action results and NPC reactions"""
        # Load agent and task from YAML
        agent = self._load_agent_config("narrative_generator")
        task = self._load_task_config("narrative_task", agent, NarrativeOutput)

        # Execute task
        result = self._execute_task_sync(task, {
            "campaign": self.state.campaign,
            "player": self.state.player,
            "current_venue": self.state.current_venue,
            "action": str(self.state.action or self.state.action_extracted),
            "effect": self.state.effect or "",
            "reactions": str(self.state.reactions)
        })

        # Update state
        self.state.narrative = result.narrative
        self.state.state_updates = result.state_updates

        return self.state
