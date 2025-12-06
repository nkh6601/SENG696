import yaml
import os
from pathlib import Path
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from crewai import Agent, Task, LLM
from crewai.flow.flow import Flow, listen, start, router

from dnd_mas_host.interface.message_types import Message, MessageType, create_message
from dnd_mas_host.state.host_state import Action, ActionType, WorkflowStep


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
    msg: Optional[Message] = None
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
        self.host_manager = None
        self.bb = None

    def _create_tools(self) -> dict:
        """
        Create tools for each Narrator agent based on Tool Assignment Matrix.

        Returns a dict mapping agent names to their specific tool lists.
        """
        from dnd_mas_host.tools.mongodb_vector_tools import (
            # NPCVectorSearchTool,        # DISABLED - use passed state
            # VenueVectorSearchTool,      # DISABLED - use passed state
            # StageVectorSearchTool,      # DISABLED - use passed state
            MonsterVectorSearchTool,
            SpellVectorSearchTool
        )

        return {
            # Prompt Validator: NO TOOLS - all context provided in state
            "prompt_validator": [],

            # Action Extractor: NO TOOLS - all context provided in state
            "action_extractor": [],

            # Narrative Generator: Keep D&D knowledge tools only
            "narrative_generator": [
                MonsterVectorSearchTool(),     # Combat/creature details (D&D SRD)
                SpellVectorSearchTool(),       # Spell descriptions (D&D SRD)
            ],

            # NPC Narrative Generator: Keep D&D knowledge tools only
            "npc_narrative_generator": [
                MonsterVectorSearchTool(),     # Combat/creature details (D&D SRD)
                SpellVectorSearchTool(),       # Spell descriptions (D&D SRD)
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
        if not self.state.msg:
            raise ValueError("No message provided to NarratorFlow")

        # Phase 1: Validation - prompt provided, no action
        if self.state.msg.type == MessageType.VALIDATE_PROMPT:
            self.state.workflow_phase = "validation"
            print(f"[DEBUG] Workflow phase set to: validation")
        # Phase 2: Narrative - action/effect/reactions provided
        elif self.state.msg.type == MessageType.GENERATE_NARRATIVE:
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
        print(f"[DEBUG] NarratorFlow.validate_prompt_step() called with prompt='...'")
        
        bb = self.bb
        print(bb)
        state_text = bb.praseState()

        print(state_text)
        # Load agent and task from YAML with specific tools
        agent = self._load_agent_config("prompt_validator", self.tools["prompt_validator"])
        
        print(state_text)
        task = self._load_task_config("validate_prompt", agent, ValidationOutput)
        
        
        
        print(state_text)
        # Execute task with enriched context objects
        result = self._execute_task_sync(task, {
            "state_text": str(state_text)
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
            
            # Validation failed - send error to Interface
            self.bb.write({
                "current_turn.prompt_valid": False,
                "current_turn.validation_message": self.state.validation_message
            })
            self.host_manager.send_message(create_message(
                to="Interface",
                msg_type=MessageType.VALIDATION_ERROR,
                data={"message": self.state.validation_message},
                from_agent="Narrator"
            ))
            return None

    @listen("do_extract_action")
    def extract_action_step(self):
        """Extract structured action from validated prompt"""
        # Load agent and task from YAML with specific tools
        agent = self._load_agent_config("action_extractor", self.tools["action_extractor"])
        task = self._load_task_config("action_extract", agent, ActionExtractionOutput)

        bb = self.bb
        
        mc_name = bb.read_single("game_context.main_character_name")
        state_text = bb.praseState()

        # Execute task with enriched context objects
        result = self._execute_task_sync(task, {
            "state_text": state_text
        })

        # Update state
        self.state.action_extracted = result.dict()

        
            # Validation passed - extract action and send to Judge
        action_data = self.state.action_extracted
        bb.write({
            "current_turn.prompt_valid": True,
            "current_turn.action_extracted": Action(
                action_type=ActionType(action_data.get("action_type", "other")),
                actor_name=mc_name,
                target=action_data.get("target"),
                method=action_data.get("method", ""),
                intent=action_data.get("intent", "")
            )
        })
        self.host_manager.send_message(create_message(
            to="Judge",
            msg_type=MessageType.CHECK_FEASIBILITY,
            from_agent="Narrator"
        ))
        
        return self.state

    @listen("do_generate_narrative")
    def generate_narrative_step(self):
        """Generate narrative from action results and NPC reactions"""
        # Load agent and task from YAML with specific tools
        agent = self._load_agent_config("narrative_generator", self.tools["narrative_generator"])
        task = self._load_task_config("narrative_task", agent, NarrativeOutput)

        bb = self.bb
        
        state_text = bb.praseState()
        mc_name = bb.read_single("game_context.main_character_name")
        current_turn = bb.read_single("current_turn")
        
        
        # Execute task with enriched context objects
        result = self._execute_task_sync(task, {
            "state_text": state_text,
            "action": str(current_turn.action_extracted),
            "effect": str(current_turn.mc_consequence),
        })

        # Update state
        self.state.narrative = result.narrative
        self.state.state_updates = result.state_updates

        bb.write({
            "output.final_output": {mc_name: result.narrative},
            "workflow.current_step": WorkflowStep.STEP_9_DISPLAY_OUTPUT,
            "workflow.flow_complete": True            
        })
        return self.state
    
    @listen("generate_narrative_step")
    def generate_npc_narratives_batch(self):
        """
        Generate narratives for all NPC reactions in a single batch.
        This method is called directly from HostFlow (not part of the flow routing).
        """
        if not self.state.npc_reactions:
            self.state.npc_narratives = ""
            return self.state

        # Load agent and task from YAML with specific tools
        agent = self._load_agent_config("npc_narrative_generator", self.tools["npc_narrative_generator"])
        task = self._load_task_config("generate_npc_narratives", agent, str)

        bb = self.bb
        
        state_text = bb.praseState()
        
        current_turn = bb.read_single("current_turn")

        # Build enriched NPC context from npc_reactions
        npc_context = []
        for char, reaction in current_turn.reactions_consequence_list:
            npc_context.append({
                "name": char,
                "effect": str(reaction)
            })

        # Execute task
        result = self._execute_task_sync(task, {
            "state_text": state_text,
            "npc_reactions": npc_context
        })

        # Update state with generated narratives
        self.state.npc_narratives = result if isinstance(result, str) else str(result)
        
        final_output = bb.read_single("output.final_output")        
        
        if self.narrator_flow.state.npc_narratives:
                final_output["NPCs"] = self.narrator_flow.state.npc_narratives
        
        bb.write({
            "output.final_output": final_output,
            "workflow.current_step": WorkflowStep.STEP_9_DISPLAY_OUTPUT,
            "workflow.flow_complete": True            
        })

        self.host_manager.send_message(create_message(
            to="Interface",
            msg_type=MessageType.DISPLAY_NARRATIVE,
            data={"narratives": final_output},
            from_agent="Narrator"
        ))
        
        return self.state
