"""
Data models for Interface Agent.

This module defines Pydantic models for structured data used by the
Interface Agent for conversation history and internal state management.
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict
from datetime import datetime

from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

from .character import Character
from dnd_mas_host.tools.mongodb_vector_tools import MongoDBVectorSearchConfig


class ConversationEntry(BaseModel):
    """
    Single entry in conversation history.

    Attributes:
        speaker: Speaker name ("Narrator", "Player", NPC name, "System")
        text: Message content
        timestamp: ISO format timestamp
        entry_type: Type of entry ("narrative", "prompt", "system", "difficulty", "roll")
    """
    speaker: str = Field(description="Speaker name (Narrator/Player/NPC/System)")
    text: str = Field(description="Message content")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat(), description="ISO format timestamp")
    entry_type: str = Field(default="narrative", description="Entry type (narrative/prompt/system/difficulty/roll)")


class InterfaceState(BaseModel):
    """
    Internal state for Interface Agent.

    This tracks the GUI's internal state including game state display and thread
    coordination flags. Conversation history is now managed by GameState in GameManager.
    This is separate from HostState which tracks workflow coordination across all crews.
    """
    # Game state (synchronized from DISPLAY_NARRATIVE messages)
    campaign: str = Field(default="Humantown", description="Campaign name")
    player: str = Field(default="Adventurer", description="Player character name")
    player_class: str = Field(default="Fighter", description="Player character class")
    player_background: str = Field(default="", description="Player character background")
    character_hp: int = Field(default=20, description="Current HP")
    character_max_hp: int = Field(default=20, description="Maximum HP")
    current_stage: str = Field(default="", description="Current story stage")
    current_venue: str = Field(default="", description="Current location")

    # Character details (extended information)
    character_skills: List[str] = Field(default_factory=list, description="Character skill proficiencies")
    character_items: List[str] = Field(default_factory=list, description="Character inventory items")

    # NPC tracking
    active_npcs: List[dict] = Field(default_factory=list, description="NPCs in current venue with health")

    # Thread coordination
    flow_running: bool = Field(default=False, description="Whether HostFlow is currently executing")
    awaiting_difficulty_decision: bool = Field(default=False, description="Whether GUI is waiting for user difficulty decision")
    current_difficulty: Optional[int] = Field(default=None, description="Current difficulty DC if awaiting decision")


class Venue(BaseModel):
    """
    Represents a game venue/location.

    This structured model replaces string-based venue references with
    rich context including environment, NPCs, connections, and available actions.
    """
    name: str = Field(description="Venue identifier/name")
    env_desc: str = Field(default="", description="Environmental description (lighting, terrain, hazards)")
    story_desc: str = Field(default="", description="Story-relevant description")
    connect_venues: List[str] = Field(default_factory=list, description="Connected venue names")
    npcs_present: List[str] = Field(default_factory=list, description="NPC names in this venue")
    supported_actions: List[str] = Field(default_factory=list, description="Available action types")

    class Config:
        extra = "allow"  # Allow additional fields from MongoDB


class Stage(BaseModel):
    """
    Represents a story stage.

    This structured model provides context about the current story progression,
    including available venues and narrative context.
    """
    name: str = Field(description="Stage identifier/name")
    env_desc: str = Field(default="", description="Stage environment description")
    story_desc: str = Field(default="", description="Stage story description")
    venues: List[str] = Field(default_factory=list, description="Venue names in this stage")
    start_venue: str = Field(default="", description="Starting venue name")
    start_narrative: str = Field(default="", description="Opening narrative")

    class Config:
        extra = "allow"  # Allow additional fields from MongoDB


class Campaign(BaseModel):
    """
    Full campaign data loaded from MongoDB.

    This class pre-loads ALL stages, venues, and NPCs at initialization
    for efficient access during gameplay without repeated database queries.
    """
    name: str = Field(description="Campaign name")
    objective: str = Field(default="", description="Campaign objective (win condition)")
    outline: str = Field(default="", description="Story outline/progression")
    map_description: str = Field(default="", description="Map layout description")
    start_stage: str = Field(default="", description="Starting stage name")
    start_venue: str = Field(default="", description="Starting venue name")
    start_narrative: str = Field(default="", description="Opening narrative text")

    # Fully loaded objects keyed by name
    stages: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict,
        description="All stages keyed by stage name"
    )
    all_venues: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict,
        description="All venues across campaign keyed by venue name"
    )
    all_npcs: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict,
        description="All NPCs across campaign keyed by NPC name"
    )

    class Config:
        arbitrary_types_allowed = True
        extra = "allow"

    @classmethod
    def load_from_db(
        cls,
        campaign_name: str,
        mongo_uri: str = None
    ) -> "Campaign":
        """
        Load full campaign from MongoDB with all related objects.

        This method pre-loads ALL stages, venues, and NPCs for the campaign
        into memory for efficient access during gameplay.

        Args:
            campaign_name: Name of the campaign to load (e.g., "Humantown: Rescue from the Town of Slimes")
            mongo_uri: MongoDB connection string (defaults to MongoDBVectorSearchConfig.MONGO_URI)

        Returns:
            Campaign instance with all data loaded

        Raises:
            ConnectionFailure: If MongoDB connection fails
            ValueError: If campaign not found
        """
        # Use consistent MongoDB URI from config
        if mongo_uri is None:
            mongo_uri = MongoDBVectorSearchConfig.MONGO_URI

        print(f"[Campaign] Loading campaign '{campaign_name}' from MongoDB...")
        print(f"[Campaign] Using MongoDB URI: {mongo_uri}")

        # Connect to MongoDB
        client = MongoClient(mongo_uri)
        client.admin.command('ping')  # Force connection check
        db = client["campaign"]

        try:
            # Step 1: Load campaign from 'stories' collection
            campaign_doc = db["stories"].find_one({"name": campaign_name})
            if not campaign_doc:
                raise ValueError(f"Campaign '{campaign_name}' not found in database")

            print(f"[Campaign]   - Found campaign: {campaign_doc.get('name')}")

            # Step 2: Load ALL stages
            stages = {}
            stage_cursor = db["stages"].find({})
            for stage_doc in stage_cursor:
                stage_name = stage_doc.get("name", "")
                if stage_name:
                    # Remove MongoDB _id for serialization
                    stage_doc.pop("_id", None)
                    stages[stage_name] = stage_doc
            print(f"[Campaign]   - Loaded {len(stages)} stages")

            # Step 3: Load ALL venues
            all_venues = {}
            venue_cursor = db["venues"].find({})
            for venue_doc in venue_cursor:
                venue_name = venue_doc.get("name", "")
                if venue_name:
                    # Remove MongoDB _id for serialization
                    venue_doc.pop("_id", None)
                    all_venues[venue_name] = venue_doc
            print(f"[Campaign]   - Loaded {len(all_venues)} venues")

            # Step 4: Load ALL NPCs
            all_npcs = {}
            npc_cursor = db["NPCs"].find({})
            for npc_doc in npc_cursor:
                npc_name = npc_doc.get("name", "")
                if npc_name:
                    # Convert _id to string for serialization
                    if "_id" in npc_doc:
                        npc_doc["_id"] = str(npc_doc["_id"])
                    all_npcs[npc_name] = npc_doc
            print(f"[Campaign]   - Loaded {len(all_npcs)} NPCs")

            # Create Campaign instance
            campaign = cls(
                name=campaign_doc.get("name", campaign_name),
                objective=campaign_doc.get("objective", ""),
                outline=campaign_doc.get("outline", ""),
                map_description=campaign_doc.get("mapDescription", ""),
                start_stage=campaign_doc.get("startStage", ""),
                start_venue=campaign_doc.get("startVenue", ""),
                start_narrative=campaign_doc.get("startNarrative", ""),
                stages=stages,
                all_venues=all_venues,
                all_npcs=all_npcs
            )

            print(f"[Campaign] Campaign loaded successfully!")
            return campaign

        finally:
            client.close()

    def get_stage(self, stage_name: str) -> Optional[Dict[str, Any]]:
        """Get stage data by name."""
        return self.stages.get(stage_name)

    def get_venue(self, venue_name: str) -> Optional[Dict[str, Any]]:
        """Get venue data by name."""
        return self.all_venues.get(venue_name)

    def get_npc(self, npc_name: str) -> Optional[Dict[str, Any]]:
        """Get NPC data by name."""
        return self.all_npcs.get(npc_name)

    def get_npcs_in_venue(self, venue_name: str) -> List[str]:
        """Get list of NPC names present in a venue."""
        venue = self.get_venue(venue_name)
        if venue:
            return venue.get("NPCs", [])
        return []

    def get_connected_venues(self, venue_name: str) -> List[str]:
        """Get list of venue names connected to a venue."""
        venue = self.get_venue(venue_name)
        if venue:
            return venue.get("connectVenues", [])
        return []
