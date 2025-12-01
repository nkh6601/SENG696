from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai.agents.agent_builder.base_agent import BaseAgent
from typing import List, Optional
from pydantic import BaseModel, Field


# Output models for structured task outputs
class DifficultyOutput(BaseModel):
    """Output model for check_difficulty task"""
    difficulty: int = Field(description="Difficulty level from -1 to 21")
    reasoning: str = Field(description="Reasoning about the difficulty")
    skip_check: bool = Field(default=False, description="Whether to skip difficulty check (-1 or 21)")


class ConsequencesOutput(BaseModel):
    """Output model for action result tasks"""
    effect: str = Field(description="Description of the action's impact")
    reasoning: str = Field(description="Reasoning about the consequences")
    time_used: Optional[str] = Field(default=None, description="Time the action took")


# If you want to run a snippet of code before or after the crew starts,
# you can use the @before_kickoff and @after_kickoff decorators
# https://docs.crewai.com/concepts/crews#example-crew-class-with-decorators

@CrewBase
class JudgeCrew():
    """JudgeCrew crew"""

    agents: List[BaseAgent]
    tasks: List[Task]

    # Learn more about YAML configuration files here:
    # Agents: https://docs.crewai.com/concepts/agents#yaml-configuration-recommended
    # Tasks: https://docs.crewai.com/concepts/tasks#yaml-configuration-recommended
    
    # If you would like to add tools to your agents, you can learn more about it here:
    # https://docs.crewai.com/concepts/agents#agent-tools
    @agent
    def judge(self) -> Agent:
        return Agent(
            config=self.agents_config['judge'], # type: ignore[index]
            verbose=True
        )

    # To learn more about structured task outputs,
    # task dependencies, and task callbacks, check out the documentation:
    # https://docs.crewai.com/concepts/tasks#overview-of-a-task
    @task
    def check_difficulty(self) -> Task:
        return Task(
            config=self.tasks_config['check_difficulty'], # type: ignore[index]
            output_pydantic=DifficultyOutput
        )

    @task
    def good_action_result(self) -> Task:
        return Task(
            config=self.tasks_config['good_action_result'], # type: ignore[index]
            output_pydantic=ConsequencesOutput
        )

    @task
    def bad_action_result(self) -> Task:
        return Task(
            config=self.tasks_config['bad_action_result'], # type: ignore[index]
            output_pydantic=ConsequencesOutput
        )

    @crew
    def crew(self) -> Crew:
        """Creates the JudgeCrew crew"""
        # To learn how to add knowledge sources to your crew, check out the documentation:
        # https://docs.crewai.com/concepts/knowledge#what-is-knowledge

        return Crew(
            agents=self.agents, # Automatically created by the @agent decorator
            tasks=self.tasks, # Automatically created by the @task decorator
            process=Process.sequential,
            verbose=True,
            # process=Process.hierarchical, # In case you wanna use that instead https://docs.crewai.com/how-to/Hierarchical/
        )
