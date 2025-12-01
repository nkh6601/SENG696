from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai.agents.agent_builder.base_agent import BaseAgent
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


# Output models for structured task outputs
class ValidationOutput(BaseModel):
    """Output model for validate_prompt task"""
    valid: bool = Field(description="Whether the prompt is valid")
    message: str = Field(description="Validation message or clarification request")


class ActionExtractionOutput(BaseModel):
    """Output model for action_extract task"""
    action_type: str = Field(description="Type of action (e.g., attack, investigate, talk)")
    target: str = Field(description="Target of the action")
    method: str = Field(description="Method or approach")
    intent: str = Field(description="Player's intent")


class NarrativeOutput(BaseModel):
    """Output model for narrative_task"""
    narrative: str = Field(description="Generated narrative text")
    state_updates: Dict[str, Any] = Field(default_factory=dict, description="Game state updates (HP, venue, etc.)")


# If you want to run a snippet of code before or after the crew starts,
# you can use the @before_kickoff and @after_kickoff decorators
# https://docs.crewai.com/concepts/crews#example-crew-class-with-decorators

@CrewBase
class NarratorCrew():
    """
    Narrator crew - ALL 3 tasks execute on every kickoff.

    This is intentional: the single narrator agent instance maintains
    game state (story progress, character status, combat, conversation history)
    across all three tasks. Splitting into separate crews would create independent
    agent instances, each losing the state tracked by the others.

    Trade-off: Higher token cost (all 3 tasks execute every call) vs.
    maintaining state integrity and narrative coherence.
    """

    agents: List[BaseAgent]
    tasks: List[Task]

    # Learn more about YAML configuration files here:
    # Agents: https://docs.crewai.com/concepts/agents#yaml-configuration-recommended
    # Tasks: https://docs.crewai.com/concepts/tasks#yaml-configuration-recommended
    
    # If you would like to add tools to your agents, you can learn more about it here:
    # https://docs.crewai.com/concepts/agents#agent-tools
    @agent
    def narrator(self) -> Agent:
        return Agent(
            config=self.agents_config['narrator'], # type: ignore[index]
            verbose=True
        )

    # To learn more about structured task outputs,
    # task dependencies, and task callbacks, check out the documentation:
    # https://docs.crewai.com/concepts/tasks#overview-of-a-task
    @task
    def narrative_task(self) -> Task:
        return Task(
            config=self.tasks_config['narrative_task'], # type: ignore[index]
            output_pydantic=NarrativeOutput
        )

    @task
    def validate_prompt(self) -> Task:
        return Task(
            config=self.tasks_config['validate_prompt'], # type: ignore[index]
            output_pydantic=ValidationOutput
        )


    @task
    def action_extract(self) -> Task:
        return Task(
            config=self.tasks_config['action_extract'], # type: ignore[index]
            output_pydantic=ActionExtractionOutput
        )
        
    @crew
    def crew(self) -> Crew:
        """Creates the NarratorCrew crew"""
        # To learn how to add knowledge sources to your crew, check out the documentation:
        # https://docs.crewai.com/concepts/knowledge#what-is-knowledge

        return Crew(
            agents=self.agents, # Automatically created by the @agent decorator
            tasks=self.tasks, # Automatically created by the @task decorator
            process=Process.sequential,
            verbose=True,
            # process=Process.hierarchical, # In case you wanna use that instead https://docs.crewai.com/how-to/Hierarchical/
        )
