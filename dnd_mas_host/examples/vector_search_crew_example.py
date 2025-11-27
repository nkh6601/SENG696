"""
Example: Integrating MongoDB Vector Search Tools with CrewAI Agents

This example shows how to use the vector search tools in your DnD multi-agent system.
"""

from crewai import Agent, Crew, Task, Process
from dnd_mas_host.tools.mongodb_vector_tools import (
    NPCVectorSearchTool,
    VenueVectorSearchTool,
    StageVectorSearchTool,
    UniversalVectorSearchTool
)


class EnhancedNarratorCrew:
    """
    Example Narrator Crew with Vector Search RAG capabilities
    """

    def __init__(self):
        # Initialize vector search tools
        self.npc_search = NPCVectorSearchTool()
        self.venue_search = VenueVectorSearchTool()
        self.stage_search = StageVectorSearchTool()
        self.universal_search = UniversalVectorSearchTool()

    def narrator_agent(self) -> Agent:
        """
        Narrator agent with RAG tools for context-aware storytelling
        """
        return Agent(
            role="Dungeon Master Narrator",
            goal="Create immersive, contextually accurate narratives for the DnD game",
            backstory="""You are an experienced Dungeon Master who tells rich,
            detailed stories. You use your knowledge of NPCs, locations, and story
            stages to create consistent narratives. You search the game database
            to ensure accuracy and incorporate relevant details.""",
            tools=[
                self.npc_search,
                self.venue_search,
                self.stage_search,
                self.universal_search
            ],
            verbose=True,
            allow_delegation=False
        )

    def context_researcher_agent(self) -> Agent:
        """
        Agent that gathers context from the database before narration
        """
        return Agent(
            role="Context Researcher",
            goal="Gather all relevant game context from the database",
            backstory="""You are a meticulous researcher who finds all relevant
            NPCs, locations, and story elements related to the current situation.
            You provide comprehensive context to the narrator.""",
            tools=[
                self.npc_search,
                self.venue_search,
                self.universal_search
            ],
            verbose=True,
            allow_delegation=False
        )

    def research_context_task(self, player_action: str, current_location: str) -> Task:
        """
        Task to research context before creating narrative
        """
        return Task(
            description=f"""
            Research Context for Current Situation:

            Player Action: {player_action}
            Current Location: {current_location}

            Your tasks:
            1. Search for NPCs at or near "{current_location}"
            2. Search for venue details about "{current_location}"
            3. Search for any other relevant content related to "{player_action}"
            4. Compile a comprehensive context report

            Provide:
            - List of relevant NPCs with their descriptions and motivations
            - Location details and connected venues
            - Any relevant story stage information
            - Potential consequences or related content
            """,
            agent=self.context_researcher_agent(),
            expected_output="""A comprehensive context report containing:
            1. Relevant NPCs (names, descriptions, personalities)
            2. Location details and connections
            3. Related story elements
            4. Potential narrative hooks"""
        )

    def create_narrative_task(self, player_action: str) -> Task:
        """
        Task to create narrative using researched context
        """
        return Task(
            description=f"""
            Create Narrative Response:

            Player Action: {player_action}

            Using the context gathered by the researcher:
            1. Determine which NPCs would react and how
            2. Describe environmental changes or effects
            3. Create a vivid narrative paragraph
            4. Maintain consistency with game lore

            The narrative should:
            - Be 2-4 paragraphs long
            - Include NPC reactions if relevant
            - Describe sensory details
            - Set up the next decision point for players
            """,
            agent=self.narrator_agent(),
            expected_output="""A narrative response that:
            - Describes what happens after the player's action
            - Includes appropriate NPC reactions
            - Sets up the next scene
            - Maintains consistency with the game world"""
        )

    def create_crew(self, player_action: str, current_location: str) -> Crew:
        """
        Create a crew that researches context then creates narrative
        """
        return Crew(
            agents=[
                self.context_researcher_agent(),
                self.narrator_agent()
            ],
            tasks=[
                self.research_context_task(player_action, current_location),
                self.create_narrative_task(player_action)
            ],
            process=Process.sequential,
            verbose=True
        )


class EnhancedNPCCrew:
    """
    Example NPC Crew with Vector Search for finding relevant NPCs
    """

    def __init__(self):
        self.npc_search = NPCVectorSearchTool()
        self.venue_search = VenueVectorSearchTool()

    def npc_behavior_agent(self) -> Agent:
        """
        Agent that determines NPC reactions using database search
        """
        return Agent(
            role="NPC Behavior Controller",
            goal="Determine realistic NPC reactions based on their personalities and context",
            backstory="""You control all NPCs in the game world. You search the
            database to find relevant NPCs, understand their motivations, and
            determine how they would realistically react to player actions.""",
            tools=[self.npc_search, self.venue_search],
            verbose=True,
            allow_delegation=False
        )

    def npc_reaction_task(self, player_action: str, location: str, action_type: str) -> Task:
        """
        Task to generate NPC reactions
        """
        return Task(
            description=f"""
            Generate NPC Reactions:

            Player Action: {player_action}
            Location: {location}
            Action Type: {action_type}

            Steps:
            1. Search for NPCs at "{location}"
            2. Search for NPCs who would care about "{action_type}" actions
            3. For each relevant NPC:
               - Determine if they would notice the action
               - Based on their personality, decide their reaction
               - Consider their intentions and goals
            4. Generate dialogue or behavior for reacting NPCs

            Consider:
            - NPC personalities and goals
            - Relationship between player action and NPC interests
            - Current story stage context
            """,
            agent=self.npc_behavior_agent(),
            expected_output="""List of NPC reactions containing:
            - NPC name
            - Whether they noticed the action
            - Their emotional reaction
            - Their behavioral response (dialogue/action)
            - Any consequences triggered"""
        )


class EnhancedJudgeCrew:
    """
    Example Judge Crew that uses vector search to find similar situations
    """

    def __init__(self):
        self.universal_search = UniversalVectorSearchTool()
        self.venue_search = VenueVectorSearchTool()

    def judge_agent(self) -> Agent:
        """
        Agent that judges action difficulty using precedent search
        """
        return Agent(
            role="Action Judge",
            goal="Determine difficulty and outcome of player actions fairly and consistently",
            backstory="""You judge player actions by searching for similar situations
            in the game database, considering location hazards, and applying DnD 5E rules.
            You ensure consistent difficulty ratings.""",
            tools=[self.universal_search, self.venue_search],
            verbose=True,
            allow_delegation=False
        )

    def judge_action_task(self, action: str, location: str) -> Task:
        """
        Task to judge an action's difficulty
        """
        return Task(
            description=f"""
            Judge Player Action Difficulty:

            Action: {action}
            Location: {location}

            Steps:
            1. Search venue "{location}" for hazards and features
            2. Search for similar actions in the database
            3. Consider DnD 5E difficulty standards
            4. Determine DC (Difficulty Class) from 5 to 30
            5. List potential outcomes (success vs failure)

            Provide:
            - DC number with justification
            - Success outcome description
            - Failure outcome description
            - Any special conditions or modifiers
            """,
            agent=self.judge_agent(),
            expected_output="""Action judgment containing:
            - DC: [number]
            - Justification: [why this DC]
            - Success: [what happens on success]
            - Failure: [what happens on failure]
            - Modifiers: [any situational bonuses/penalties]"""
        )


# Example Usage
def example_narrator_with_rag():
    """
    Example: Using narrator crew with RAG
    """
    print("\n" + "="*60)
    print("Example 1: Narrator Crew with Vector Search RAG")
    print("="*60)

    crew_manager = EnhancedNarratorCrew()

    crew = crew_manager.create_crew(
        player_action="I sneak into the tavern's kitchen to search for clues",
        current_location="The Tavern"
    )

    result = crew.kickoff()
    print("\n--- Narrative Result ---")
    print(result)


def example_npc_reactions():
    """
    Example: NPC crew finding and reacting
    """
    print("\n" + "="*60)
    print("Example 2: NPC Reactions Using Vector Search")
    print("="*60)

    npc_crew = EnhancedNPCCrew()

    task = npc_crew.npc_reaction_task(
        player_action="The player loudly accuses the tavern owner of hiding information",
        location="The Tavern",
        action_type="confrontation"
    )

    agent = npc_crew.npc_behavior_agent()

    # Execute task
    crew = Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=True
    )

    result = crew.kickoff()
    print("\n--- NPC Reactions ---")
    print(result)


def example_judge_with_context():
    """
    Example: Judge crew using venue context
    """
    print("\n" + "="*60)
    print("Example 3: Judge Crew with Venue Context")
    print("="*60)

    judge_crew = EnhancedJudgeCrew()

    task = judge_crew.judge_action_task(
        action="I try to climb through the broken window into the Museum",
        location="Museum Exterior"
    )

    agent = judge_crew.judge_agent()

    crew = Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=True
    )

    result = crew.kickoff()
    print("\n--- Action Judgment ---")
    print(result)


def example_direct_tool_usage():
    """
    Example: Using tools directly without crews
    """
    print("\n" + "="*60)
    print("Example 4: Direct Tool Usage")
    print("="*60)

    # Search for hostile NPCs
    npc_tool = NPCVectorSearchTool()
    print("\n--- Searching for hostile NPCs ---")
    result = npc_tool._run(query="hostile dangerous enemies", limit=3)
    print(result)

    # Search for safe locations
    venue_tool = VenueVectorSearchTool()
    print("\n--- Searching for safe locations ---")
    result = venue_tool._run(query="safe places to rest and recover", limit=3)
    print(result)

    # Universal search
    universal_tool = UniversalVectorSearchTool()
    print("\n--- Universal search for 'slime' ---")
    result = universal_tool._run(query="slime creatures and experiments", limit=2)
    print(result)


if __name__ == "__main__":
    """
    Run examples

    NOTE: Make sure you've run scripts/create_vector_indexes.py first!
    """
    print("\n" + "#"*60)
    print("# Vector Search Integration Examples")
    print("#"*60)
    print("\nPrerequisites:")
    print("1. MongoDB running at mongodb://127.0.0.1:27017/")
    print("2. Embeddings generated (run scripts/create_vector_indexes.py)")
    print("3. Vector search indexes created")
    print("#"*60)

    choice = input("\nWhich example to run? (1-4, or 'all'): ").strip()

    if choice == "1":
        example_narrator_with_rag()
    elif choice == "2":
        example_npc_reactions()
    elif choice == "3":
        example_judge_with_context()
    elif choice == "4":
        example_direct_tool_usage()
    elif choice.lower() == "all":
        example_direct_tool_usage()
        example_npc_reactions()
        example_judge_with_context()
        example_narrator_with_rag()
    else:
        print("Invalid choice. Run with: python examples/vector_search_crew_example.py")
