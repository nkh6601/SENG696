#!/usr/bin/env python
from random import randint
from typing import List, Dict
from datetime import datetime

from pydantic import BaseModel, Field

from crewai.flow import Flow, listen, start

from dnd_mas_host.crews.judge_crew.judge_crew import JudgeCrew

from dnd_mas_host.crews.narrator_crew.narrator_crew import NarratorCrew

from dnd_mas_host.crews.npc_crew.npc_crew import NpcCrew

from dnd_mas_host.crews.poem_crew.poem_crew import PoemCrew


class HostState(BaseModel):
    # Workflow tracking
    current_step: str = Field(default="", description="Current step in the workflow")
    current_agent: str = Field(default="", description="Name of the agent currently processing")
    error_log: List[Dict[str, str]] = Field(default_factory=list, description="List of errors log")
    retry_count: Dict[str, int] = Field(default_factory=dict, description='Number of retries per crew: {"crew_a": 2}')
    pipeline_branch: Dict[str, str] = Field(default_factory=dict, description='Current conditional branch (e.g., "success", "failed", "retry") for router logic')

    # Timestamps
    start_time: str = Field(default_factory=lambda: datetime.now().isoformat(), description="Timestamp of workflow start")
    last_updated: str = Field(default_factory=lambda: datetime.now().isoformat(), description="Timestamp of last state update")

    # User input and action processing
    prompt_text: str = Field(default="", description="Current user's prompt being processed")
    Action_difficulty: Dict[str, int] = Field(default_factory=dict, description="Extracted action obtained from the prompt by the Narrator Agent, and its corresponding difficulty by the Judge Agent")
    difficulty_check: int = Field(default=0, description="The difficulty check result obtained by the Interface agent")

    # Action effects and reactions
    effect: str = Field(default="", description="The effect of action that evaluated by Judge Agent")
    reactions: List[Dict[str, str | int]] = Field(default_factory=list, description="List of reactions obtained from the NPC agents, and their corresponding difficulty by the Judge Agent")

    # Output and story impact
    final_output: str = Field(default="", description="Final generated narrative of both user's action, its effects, and NPCs reactions")
    Impact_stage: List[tuple[str, str]] = Field(default_factory=list, description="The accumulated impact on the story, including the death of the NPC, triggered trap, and destroyed some buildings... Separated in stages")



class HostFlow(Flow[HostState]):

    @start()
    def generate_sentence_count(self, crewai_trigger_payload: dict = None):
        print("Initial string")

        # Use trigger payload if available
        if crewai_trigger_payload:
            # Example: use trigger data to influence sentence count
            self.state.sentence_count = crewai_trigger_payload.get('sentence_count', randint(1, 5))
            print(f"Using trigger payload: {crewai_trigger_payload}")
        else:
            self.state.sentence_count = randint(1, 5)

    @listen(generate_sentence_count)
    def generate_Host(self):
        print("Generating Host")
        result = (
            PoemCrew()
            .crew()
            .kickoff(inputs={"sentence_count": self.state.sentence_count})
        )

        print("Host generated", result.raw)
        self.state.Host = result.raw

    @listen(generate_Host)
    def save_Host(self):
        print("Saving Host")
        with open("Host.txt", "w") as f:
            f.write(self.state.Host)


def kickoff():
    Host_flow = HostFlow()
    Host_flow.kickoff()


def plot():
    Host_flow = HostFlow()
    Host_flow.plot()


def run_with_trigger():
    """
    Run the flow with trigger payload.
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

    # Create flow and kickoff with trigger payload
    # The @start() methods will automatically receive crewai_trigger_payload parameter
    Host_flow = HostFlow()

    try:
        result = Host_flow.kickoff({"crewai_trigger_payload": trigger_payload})
        return result
    except Exception as e:
        raise Exception(f"An error occurred while running the flow with trigger: {e}")


if __name__ == "__main__":
    kickoff()
