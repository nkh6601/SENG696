from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai.agents.agent_builder.base_agent import BaseAgent
from typing import List
from pydantic import BaseModel, Field


# Output models for structured task outputs
class ReactionCheckOutput(BaseModel):
    """Output model for if_reaction task"""
    has_reaction: bool = Field(description="Whether the NPC has a reaction")
    reasoning: str = Field(description="Reasoning about the reaction decision")


class ReactionOutput(BaseModel):
    """Output model for extract_reaction task - structured like player actions"""
    action_type: str = Field(description="Type of reaction action (attack, cast spell, move, dodge, etc.)")
    target: str = Field(description="Target of the reaction")
    method: str = Field(description="Method or approach for the reaction")
    intent: str = Field(description="Character's intent with this reaction")


# If you want to run a snippet of code before or after the crew starts,
# you can use the @before_kickoff and @after_kickoff decorators
# https://docs.crewai.com/concepts/crews#example-crew-class-with-decorators

@CrewBase
class NpcCrew():
    """NpcCrew crew"""

    agents: List[BaseAgent]
    tasks: List[Task]

    # Learn more about YAML configuration files here:
    # Agents: https://docs.crewai.com/concepts/agents#yaml-configuration-recommended
    # Tasks: https://docs.crewai.com/concepts/tasks#yaml-configuration-recommended
    
    # If you would like to add tools to your agents, you can learn more about it here:
    # https://docs.crewai.com/concepts/agents#agent-tools
    @agent
    def npc(self) -> Agent:
        # Import execution control settings
        from dnd_mas_host.config import MAX_ITER, MAX_EXECUTION_TIME, MAX_RPM, MAX_RETRY_LIMIT

        return Agent(
            config=self.agents_config['NPC'], # type: ignore[index]
            verbose=True,
            max_iter=MAX_ITER,
            max_execution_time=MAX_EXECUTION_TIME,
            max_rpm=MAX_RPM,
            max_retry_limit=MAX_RETRY_LIMIT
        )

    # To learn more about structured task outputs,
    # task dependencies, and task callbacks, check out the documentation:
    # https://docs.crewai.com/concepts/tasks#overview-of-a-task
    @task
    def if_reaction(self) -> Task:
        return Task(
            config=self.tasks_config['if_reaction'], # type: ignore[index]
            output_pydantic=ReactionCheckOutput
        )

    @task
    def extract_reaction(self) -> Task:
        return Task(
            config=self.tasks_config['extract_reaction'], # type: ignore[index]
            output_pydantic=ReactionOutput
        )

    @crew
    def crew(self) -> Crew:
        """Creates the NpcCrew crew"""
        # To learn how to add knowledge sources to your crew, check out the documentation:
        # https://docs.crewai.com/concepts/knowledge#what-is-knowledge

        return Crew(
            agents=self.agents, # Automatically created by the @agent decorator
            tasks=self.tasks, # Automatically created by the @task decorator
            process=Process.sequential,
            verbose=True,
            # process=Process.hierarchical, # In case you wanna use that instead https://docs.crewai.com/how-to/Hierarchical/
        )
