"""
MongoDB Vector Search Tools for DnD Multi-Agent System
Provides RAG capabilities using local embeddings for NPCs, Venues, Stages, and Stories
"""

from typing import List, Dict, Any, Optional
from pymongo import MongoClient
from sentence_transformers import SentenceTransformer
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
import numpy as np


class MongoDBVectorSearchConfig:
    """Configuration for MongoDB Vector Search"""

    # MongoDB Connection
    MONGO_URI = "mongodb://127.0.0.1:27017/?directConnection=true&serverSelectionTimeoutMS=2000"

    # Databases
    DATABASE_CAMPAIGN = "campaign"
    DATABASE_5E = "5e-database"

    # Campaign Collections
    COLLECTIONS_CAMPAIGN = {
        "npcs": "npcs",
        "venues": "venues",
        "stages": "stages",
        "stories": "stories"
    }

    # 5E Database Collections
    COLLECTIONS_5E = {
        "monsters": "2014-monsters",
        "spells": "2014-spells",
        "rules": "2014-rules",
        "equipment": "2014-equipment",
        "classes": "2014-classes",
        "conditions": "2014-conditions",
        "magic_items": "2014-magic-items"
    }

    # Embedding Model Configuration
    # Using all-mpnet-base-v2: 768 dimensions, high quality local model
    EMBEDDING_MODEL_NAME = "all-mpnet-base-v2"
    EMBEDDING_DIMENSIONS = 768

    # Vector Index Names for Campaign Collections
    VECTOR_INDEX_NAMES_CAMPAIGN = {
        "npcs": f"vector_index_npcs_mpnet_base_v2_{EMBEDDING_DIMENSIONS}",
        "venues": f"vector_index_venues_mpnet_base_v2_{EMBEDDING_DIMENSIONS}",
        "stages": f"vector_index_stages_mpnet_base_v2_{EMBEDDING_DIMENSIONS}",
        "stories": f"vector_index_stories_mpnet_base_v2_{EMBEDDING_DIMENSIONS}"
    }

    # Vector Index Names for 5E Collections
    VECTOR_INDEX_NAMES_5E = {
        "monsters": f"vector_index_2014_monsters_mpnet_base_v2_{EMBEDDING_DIMENSIONS}",
        "spells": f"vector_index_2014_spells_mpnet_base_v2_{EMBEDDING_DIMENSIONS}",
        "rules": f"vector_index_2014_rules_mpnet_base_v2_{EMBEDDING_DIMENSIONS}",
        "equipment": f"vector_index_2014_equipment_mpnet_base_v2_{EMBEDDING_DIMENSIONS}",
        "classes": f"vector_index_2014_classes_mpnet_base_v2_{EMBEDDING_DIMENSIONS}",
        "conditions": f"vector_index_2014_conditions_mpnet_base_v2_{EMBEDDING_DIMENSIONS}",
        "magic_items": f"vector_index_2014_magic_items_mpnet_base_v2_{EMBEDDING_DIMENSIONS}"
    }

    # Fields to embed for Campaign collections
    EMBEDDING_FIELDS_CAMPAIGN = {
        "npcs": ["name", "desc", "personality", "intention", "target"],
        "venues": ["name", "envDesc", "storyDesc"],
        "stages": ["name", "envDesc", "storyDesc", "startNarrative"],
        "stories": ["name", "startNarrative", "objective", "outline", "mapDesc"]
    }

    # Fields to embed for 5E collections
    EMBEDDING_FIELDS_5E = {
        "monsters": ["name", "desc", "alignment", "type", "subtype", "size"],
        "spells": ["name", "desc", "higher_level", "components", "material"],
        "rules": ["name", "desc"],
        "equipment": ["name", "category_range", "weapon_category"],
        "classes": ["name", "class_levels", "spells"],
        "conditions": ["name", "desc"],
        "magic_items": ["name", "desc"]
    }

    # Vector field name in documents
    VECTOR_FIELD = "embedding_vector"

    # Search Configuration
    DEFAULT_NUM_CANDIDATES = 100
    DEFAULT_LIMIT = 5


class EmbeddingGenerator:
    """Generates embeddings using local SentenceTransformer model"""

    _instance = None
    _model = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._model is None:
            print(f"Loading embedding model: {MongoDBVectorSearchConfig.EMBEDDING_MODEL_NAME}")
            self._model = SentenceTransformer(MongoDBVectorSearchConfig.EMBEDDING_MODEL_NAME)
            print(f"Model loaded. Embedding dimension: {MongoDBVectorSearchConfig.EMBEDDING_DIMENSIONS}")

    def generate_embedding(self, text: str) -> List[float]:
        """Generate embedding vector for a single text"""
        embedding = self._model.encode(text, convert_to_numpy=True)
        return embedding.tolist()

    def generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embedding vectors for multiple texts"""
        embeddings = self._model.encode(texts, convert_to_numpy=True)
        return embeddings.tolist()


class MongoDBVectorSearch:
    """MongoDB Vector Search Operations"""

    def __init__(self, database: str = "campaign"):
        """
        Initialize MongoDB Vector Search

        Args:
            database: "campaign" or "5e-database"
        """
        self.client = MongoClient(MongoDBVectorSearchConfig.MONGO_URI)
        self.database = database

        if database == "campaign":
            self.db = self.client[MongoDBVectorSearchConfig.DATABASE_CAMPAIGN]
            self.collections = MongoDBVectorSearchConfig.COLLECTIONS_CAMPAIGN
            self.vector_indexes = MongoDBVectorSearchConfig.VECTOR_INDEX_NAMES_CAMPAIGN
            self.embedding_fields = MongoDBVectorSearchConfig.EMBEDDING_FIELDS_CAMPAIGN
        elif database == "5e-database":
            self.db = self.client[MongoDBVectorSearchConfig.DATABASE_5E]
            self.collections = MongoDBVectorSearchConfig.COLLECTIONS_5E
            self.vector_indexes = MongoDBVectorSearchConfig.VECTOR_INDEX_NAMES_5E
            self.embedding_fields = MongoDBVectorSearchConfig.EMBEDDING_FIELDS_5E
        else:
            raise ValueError(f"Invalid database: {database}. Must be 'campaign' or '5e-database'")

        self.embedding_generator = EmbeddingGenerator()

    def search_collection(
        self,
        collection_name: str,
        query_text: str,
        num_candidates: int = MongoDBVectorSearchConfig.DEFAULT_NUM_CANDIDATES,
        limit: int = MongoDBVectorSearchConfig.DEFAULT_LIMIT,
        filter_dict: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Perform vector search on a specific collection

        Args:
            collection_name: Name of collection to search
            query_text: Natural language query
            num_candidates: Number of candidates for vector search
            limit: Maximum results to return
            filter_dict: Optional MongoDB filter to apply

        Returns:
            List of matching documents with scores
        """
        # Generate query embedding
        query_embedding = self.embedding_generator.generate_embedding(query_text)

        # Get collection and index name
        collection = self.db[self.collections[collection_name]]
        index_name = self.vector_indexes[collection_name]

        # Build vector search pipeline
        pipeline = [
            {
                "$vectorSearch": {
                    "index": index_name,
                    "path": MongoDBVectorSearchConfig.VECTOR_FIELD,
                    "queryVector": query_embedding,
                    "numCandidates": num_candidates,
                    "limit": limit
                }
            },
            {
                "$addFields": {
                    "search_score": {"$meta": "vectorSearchScore"}
                }
            }
        ]

        # Add filter if provided
        if filter_dict:
            pipeline.insert(1, {"$match": filter_dict})

        # Execute search
        results = list(collection.aggregate(pipeline))

        # Convert ObjectId to string for JSON serialization
        for doc in results:
            if "_id" in doc:
                doc["_id"] = str(doc["_id"])

        return results

    def search_all_collections(
        self,
        query_text: str,
        limit_per_collection: int = 3
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Search across all collections and return combined results

        Args:
            query_text: Natural language query
            limit_per_collection: Max results per collection

        Returns:
            Dictionary with collection names as keys and results as values
        """
        results = {}

        for collection_name in self.collections.keys():
            try:
                results[collection_name] = self.search_collection(
                    collection_name=collection_name,
                    query_text=query_text,
                    limit=limit_per_collection
                )
            except Exception as e:
                print(f"Error searching {collection_name}: {e}")
                results[collection_name] = []

        return results


# CrewAI Tool Input Schema
class VectorSearchInput(BaseModel):
    """Input schema for vector search tools"""
    query: str = Field(..., description="Natural language search query to find relevant game content")
    limit: int = Field(default=5, description="Maximum number of results to return")


class NPCVectorSearchTool(BaseTool):
    """Tool for searching NPCs using vector similarity"""

    name: str = "Search NPCs"
    description: str = (
        "Search for NPCs (Non-Player Characters) using natural language queries. "
        "Use this to find NPCs based on their descriptions, personalities, intentions, or roles. "
        "Examples: 'Find hostile NPCs', 'NPCs who can provide information', 'characters in the tavern'"
    )
    args_schema: type[BaseModel] = VectorSearchInput

    def _run(self, query: str, limit: int = 5) -> str:
        """Execute NPC vector search"""
        searcher = MongoDBVectorSearch()
        results = searcher.search_collection("npcs", query, limit=limit)

        if not results:
            return "No NPCs found matching your query."

        # Format results for agent consumption
        formatted_results = []
        for i, npc in enumerate(results, 1):
            formatted_results.append(
                f"{i}. {npc.get('name', 'Unknown')} (Score: {npc.get('search_score', 0):.3f})\n"
                f"   Description: {npc.get('desc', 'N/A')}\n"
                f"   Personality: {npc.get('personality', 'N/A')}\n"
                f"   Intention: {npc.get('intention', 'N/A')}"
            )

        return "\n\n".join(formatted_results)


class VenueVectorSearchTool(BaseTool):
    """Tool for searching venues/locations using vector similarity"""

    name: str = "Search Venues"
    description: str = (
        "Search for venues and locations using natural language queries. "
        "Use this to find locations based on their descriptions, environmental features, or story relevance. "
        "Examples: 'Find dangerous locations', 'places with treasure', 'indoor locations', 'locations related to combat'"
    )
    args_schema: type[BaseModel] = VectorSearchInput

    def _run(self, query: str, limit: int = 5) -> str:
        """Execute venue vector search"""
        searcher = MongoDBVectorSearch()
        results = searcher.search_collection("venues", query, limit=limit)

        if not results:
            return "No venues found matching your query."

        # Format results
        formatted_results = []
        for i, venue in enumerate(results, 1):
            formatted_results.append(
                f"{i}. {venue.get('name', 'Unknown')} (Score: {venue.get('search_score', 0):.3f})\n"
                f"   Environment: {venue.get('envDesc', 'N/A')}\n"
                f"   Story: {venue.get('storyDesc', 'N/A')}\n"
                f"   Connected to: {', '.join(venue.get('connectVenues', []))}"
            )

        return "\n\n".join(formatted_results)


class StageVectorSearchTool(BaseTool):
    """Tool for searching story stages using vector similarity"""

    name: str = "Search Story Stages"
    description: str = (
        "Search for story stages/chapters using natural language queries. "
        "Use this to find stages based on their narrative content, environment, or objectives. "
        "Examples: 'Find investigation stages', 'combat-focused stages', 'stages in museums'"
    )
    args_schema: type[BaseModel] = VectorSearchInput

    def _run(self, query: str, limit: int = 5) -> str:
        """Execute stage vector search"""
        searcher = MongoDBVectorSearch()
        results = searcher.search_collection("stages", query, limit=limit)

        if not results:
            return "No story stages found matching your query."

        # Format results
        formatted_results = []
        for i, stage in enumerate(results, 1):
            formatted_results.append(
                f"{i}. {stage.get('name', 'Unknown')} (Score: {stage.get('search_score', 0):.3f})\n"
                f"   Environment: {stage.get('envDesc', 'N/A')}\n"
                f"   Story: {stage.get('storyDesc', 'N/A')[:200]}..."
            )

        return "\n\n".join(formatted_results)


class UniversalVectorSearchTool(BaseTool):
    """Tool for searching across ALL collections"""

    name: str = "Search All Game Content"
    description: str = (
        "Search across ALL game content (NPCs, venues, stages, stories) using natural language. "
        "Use this for broad queries when you're not sure which type of content to search. "
        "Examples: 'Find everything related to slimes', 'content about the windmill', 'Alistair Porridgepot'"
    )
    args_schema: type[BaseModel] = VectorSearchInput

    def _run(self, query: str, limit: int = 3) -> str:
        """Execute universal vector search across all collections"""
        searcher = MongoDBVectorSearch()
        results = searcher.search_all_collections(query, limit_per_collection=limit)

        # Format results by collection
        formatted_output = []

        for collection_name, docs in results.items():
            if docs:
                formatted_output.append(f"\n=== {collection_name.upper()} ===")
                for i, doc in enumerate(docs, 1):
                    name = doc.get('name', 'Unknown')
                    score = doc.get('search_score', 0)
                    formatted_output.append(f"{i}. {name} (Score: {score:.3f})")

                    # Add relevant description field
                    if 'desc' in doc:
                        formatted_output.append(f"   {doc['desc'][:150]}...")
                    elif 'envDesc' in doc:
                        formatted_output.append(f"   {doc['envDesc'][:150]}...")
                    elif 'storyDesc' in doc:
                        formatted_output.append(f"   {doc['storyDesc'][:150]}...")

        if not formatted_output:
            return "No content found matching your query across any collection."

        return "\n".join(formatted_output)


# ===== Game State Search Tool =====

class GameStateSearchInput(BaseModel):
    """Input schema for game state search tool"""
    query_fields: List[str] = Field(
        ...,
        description="Fields to retrieve: 'character_hp', 'character_max_hp', 'current_venue', 'current_stage', 'character_inventory', 'character_spell_slots', 'active_conditions', 'campaign', 'player'"
    )


class GameStateSearchTool(BaseTool):
    """Tool for querying structured game state data from HostState and MongoDB"""

    name: str = "Query Game State"
    description: str = (
        "Retrieve current game state information including character HP, inventory, "
        "spell slots, location, active conditions, and other character/game data. "
        "Use this to check current status before evaluating actions. "
        "Examples: query_fields=['character_hp', 'character_max_hp'] or "
        "query_fields=['character_inventory', 'character_spell_slots', 'active_conditions']"
    )
    args_schema: type[BaseModel] = GameStateSearchInput

    def __init__(self, host_state):
        """
        Initialize GameStateSearchTool with HostState reference

        Args:
            host_state: HostState object from main.py containing current game state
        """
        super().__init__()
        self.host_state = host_state
        self.mongo_client = MongoClient(MongoDBVectorSearchConfig.MONGO_URI)
        self.db = self.mongo_client[MongoDBVectorSearchConfig.DATABASE_CAMPAIGN]

    def _run(self, query_fields: List[str]) -> str:
        """
        Query game state fields from HostState and MongoDB

        Args:
            query_fields: List of field names to retrieve

        Returns:
            Formatted string with game state information
        """
        results = {}

        # Query HostState fields directly
        hoststate_fields = ['campaign', 'player', 'current_venue', 'current_stage',
                            'character_hp', 'character_max_hp']

        for field in query_fields:
            if field in hoststate_fields and hasattr(self.host_state, field):
                results[field] = getattr(self.host_state, field)

        # Query MongoDB for extended character data if needed
        extended_fields = ['character_inventory', 'character_spell_slots', 'active_conditions']
        if any(f in query_fields for f in extended_fields):
            try:
                # Find player character document
                player_doc = self.db.player_characters.find_one(
                    {"name": self.host_state.player}
                )

                if player_doc:
                    if 'character_inventory' in query_fields:
                        results['character_inventory'] = player_doc.get('inventory', [])
                    if 'character_spell_slots' in query_fields:
                        results['character_spell_slots'] = player_doc.get('spell_slots', {})
                    if 'active_conditions' in query_fields:
                        results['active_conditions'] = player_doc.get('active_conditions', [])
                else:
                    # Player character not found in DB - return empty values
                    if 'character_inventory' in query_fields:
                        results['character_inventory'] = []
                    if 'character_spell_slots' in query_fields:
                        results['character_spell_slots'] = {}
                    if 'active_conditions' in query_fields:
                        results['active_conditions'] = []

            except Exception as e:
                print(f"Error querying extended character data: {e}")
                # Return empty values on error
                for field in extended_fields:
                    if field in query_fields and field not in results:
                        results[field] = [] if field != 'character_spell_slots' else {}

        # Format output for agent consumption
        return self._format_game_state(results)

    def _format_game_state(self, results: Dict[str, Any]) -> str:
        """Format game state results as readable string"""
        output = []

        # Character and location info
        if 'player' in results:
            output.append(f"Character: {results['player']}")

        if 'character_hp' in results and 'character_max_hp' in results:
            hp = results['character_hp']
            max_hp = results['character_max_hp']
            hp_percent = int((hp / max_hp * 100)) if max_hp > 0 else 0
            output.append(f"HP: {hp}/{max_hp} ({hp_percent}%)")

        if 'current_venue' in results:
            venue_str = f"Location: {results['current_venue']}"
            if 'current_stage' in results:
                venue_str += f" (Stage: {results['current_stage']})"
            output.append(venue_str)

        if 'campaign' in results:
            output.append(f"Campaign: {results['campaign']}")

        # Inventory
        if 'character_inventory' in results:
            inventory = results['character_inventory']
            output.append("\nInventory:")
            if inventory:
                for item in inventory:
                    if isinstance(item, dict):
                        item_name = item.get('name', 'Unknown Item')
                        item_count = item.get('count', 1)
                        if item_count > 1:
                            output.append(f"- {item_name} ({item_count})")
                        else:
                            output.append(f"- {item_name}")
                    else:
                        output.append(f"- {item}")
            else:
                output.append("- Empty")

        # Spell Slots
        if 'character_spell_slots' in results:
            spell_slots = results['character_spell_slots']
            output.append("\nSpell Slots:")
            if spell_slots:
                for level, slots in spell_slots.items():
                    if isinstance(slots, dict):
                        current = slots.get('current', 0)
                        maximum = slots.get('max', 0)
                        output.append(f"- Level {level}: {current}/{maximum}")
                    else:
                        output.append(f"- Level {level}: {slots}")
            else:
                output.append("- None (not a spellcaster)")

        # Active Conditions
        if 'active_conditions' in results:
            conditions = results['active_conditions']
            output.append("\nActive Conditions:")
            if conditions:
                for condition in conditions:
                    if isinstance(condition, dict):
                        cond_name = condition.get('name', 'Unknown')
                        cond_duration = condition.get('duration', '')
                        output.append(f"- {cond_name}" + (f" ({cond_duration})" if cond_duration else ""))
                    else:
                        output.append(f"- {condition}")
            else:
                output.append("- None")

        return "\n".join(output) if output else "No game state information available."


# ===== D&D 5E Database Vector Search Tools =====


class MonsterVectorSearchTool(BaseTool):
    """Tool for searching D&D 5E monsters using vector similarity"""

    name: str = "Search D&D 5E Monsters"
    description: str = (
        "Search for D&D 5E monsters and creatures using natural language queries. "
        "Use this to find creature stats, abilities, resistances, and vulnerabilities. "
        "Examples: 'Find undead creatures', 'monsters with fire resistance', 'large beasts', 'creatures with legendary actions'"
    )
    args_schema: type[BaseModel] = VectorSearchInput

    def _run(self, query: str, limit: int = 5) -> str:
        """Execute monster vector search"""
        searcher = MongoDBVectorSearch(database="5e-database")
        results = searcher.search_collection("monsters", query, limit=limit)

        if not results:
            return "No monsters found matching your query."

        # Format results for agent consumption
        formatted_results = []
        for i, monster in enumerate(results, 1):
            # Get basic stats
            name = monster.get('name', 'Unknown')
            size = monster.get('size', 'N/A')
            type_str = monster.get('type', 'N/A')
            alignment = monster.get('alignment', 'N/A')

            # Get combat stats
            hp_str = f"{monster.get('hit_points', 'N/A')}" if 'hit_points' in monster else 'N/A'
            ac_info = monster.get('armor_class', [{}])[0] if monster.get('armor_class') else {}
            ac = ac_info.get('value', 'N/A') if isinstance(ac_info, dict) else 'N/A'

            # Get ability scores
            stats = []
            for stat in ['strength', 'dexterity', 'constitution', 'intelligence', 'wisdom', 'charisma']:
                if stat in monster:
                    stats.append(f"{stat[:3].upper()} {monster[stat]}")
            stats_str = ', '.join(stats) if stats else 'N/A'

            # Get special abilities count
            special_abilities = monster.get('special_abilities', [])
            abilities_count = len(special_abilities) if special_abilities else 0

            formatted_results.append(
                f"{i}. {name} (Score: {monster.get('search_score', 0):.3f})\n"
                f"   Type: {size} {type_str} ({alignment})\n"
                f"   HP: {hp_str}, AC: {ac}\n"
                f"   Stats: {stats_str}\n"
                f"   Special Abilities: {abilities_count}"
            )

        return "\n\n".join(formatted_results)


class SpellVectorSearchTool(BaseTool):
    """Tool for searching D&D 5E spells using vector similarity"""

    name: str = "Search D&D 5E Spells"
    description: str = (
        "Search for D&D 5E spells using natural language queries. "
        "Use this to find spell mechanics, components, damage, duration, and effects. "
        "Examples: 'Find fire damage spells', 'spells requiring concentration', 'healing spells', 'cantrips for wizards'"
    )
    args_schema: type[BaseModel] = VectorSearchInput

    def _run(self, query: str, limit: int = 5) -> str:
        """Execute spell vector search"""
        searcher = MongoDBVectorSearch(database="5e-database")
        results = searcher.search_collection("spells", query, limit=limit)

        if not results:
            return "No spells found matching your query."

        # Format results
        formatted_results = []
        for i, spell in enumerate(results, 1):
            name = spell.get('name', 'Unknown')
            level = spell.get('level', 'N/A')
            school = spell.get('school', {}).get('name', 'N/A') if isinstance(spell.get('school'), dict) else 'N/A'

            # Get casting details
            casting_time = spell.get('casting_time', 'N/A')
            range_str = spell.get('range', 'N/A')
            duration = spell.get('duration', 'N/A')

            # Get components
            components = []
            if spell.get('components'):
                comp_list = spell['components']
                if 'V' in comp_list: components.append('V')
                if 'S' in comp_list: components.append('S')
                if 'M' in comp_list: components.append(f"M ({spell.get('material', 'materials')})")
            components_str = ', '.join(components) if components else 'N/A'

            # Get description (first 150 chars)
            desc = spell.get('desc', ['N/A'])
            desc_text = desc[0][:150] + "..." if isinstance(desc, list) and desc else "N/A"

            formatted_results.append(
                f"{i}. {name} (Score: {spell.get('search_score', 0):.3f})\n"
                f"   Level: {level} ({school})\n"
                f"   Casting: {casting_time} | Range: {range_str} | Duration: {duration}\n"
                f"   Components: {components_str}\n"
                f"   Effect: {desc_text}"
            )

        return "\n\n".join(formatted_results)


class RuleVectorSearchTool(BaseTool):
    """Tool for searching D&D 5E rules using vector similarity"""

    name: str = "Search D&D 5E Rules"
    description: str = (
        "Search for D&D 5E official rules using natural language queries. "
        "Use this to find rules about combat, spellcasting, movement, actions, conditions, and game mechanics. "
        "Examples: 'Find rules about grappling', 'spellcasting rules', 'action economy', 'opportunity attacks'"
    )
    args_schema: type[BaseModel] = VectorSearchInput

    def _run(self, query: str, limit: int = 5) -> str:
        """Execute rule vector search"""
        searcher = MongoDBVectorSearch(database="5e-database")
        results = searcher.search_collection("rules", query, limit=limit)

        if not results:
            return "No rules found matching your query."

        # Format results
        formatted_results = []
        for i, rule in enumerate(results, 1):
            name = rule.get('name', 'Unknown')
            desc = rule.get('desc', 'N/A')

            # Truncate description if too long
            if isinstance(desc, str) and len(desc) > 300:
                desc = desc[:300] + "..."

            formatted_results.append(
                f"{i}. {name} (Score: {rule.get('search_score', 0):.3f})\n"
                f"   {desc}"
            )

        return "\n\n".join(formatted_results)


class EquipmentVectorSearchTool(BaseTool):
    """Tool for searching D&D 5E equipment using vector similarity"""

    name: str = "Search D&D 5E Equipment"
    description: str = (
        "Search for D&D 5E equipment including weapons, armor, and adventuring gear. "
        "Use this to find equipment stats, damage, properties, weight, and cost. "
        "Examples: 'Find martial weapons', 'heavy armor', 'ranged weapons', 'equipment for climbing'"
    )
    args_schema: type[BaseModel] = VectorSearchInput

    def _run(self, query: str, limit: int = 5) -> str:
        """Execute equipment vector search"""
        searcher = MongoDBVectorSearch(database="5e-database")
        results = searcher.search_collection("equipment", query, limit=limit)

        if not results:
            return "No equipment found matching your query."

        # Format results
        formatted_results = []
        for i, equipment in enumerate(results, 1):
            name = equipment.get('name', 'Unknown')
            category = equipment.get('equipment_category', {}).get('name', 'N/A')

            # Get equipment-specific details
            details = []

            # Weapon details
            if 'damage' in equipment:
                damage_info = equipment['damage']
                damage_str = f"{damage_info.get('damage_dice', 'N/A')} {damage_info.get('damage_type', {}).get('name', '')}"
                details.append(f"Damage: {damage_str}")

            # Armor details
            if 'armor_class' in equipment:
                ac_info = equipment['armor_class']
                ac_base = ac_info.get('base', 'N/A')
                details.append(f"AC: {ac_base}")

            # Properties
            if 'properties' in equipment:
                props = [p.get('name', '') for p in equipment['properties'] if isinstance(p, dict)]
                if props:
                    details.append(f"Properties: {', '.join(props)}")

            # Weight and cost
            weight = equipment.get('weight', 'N/A')
            cost = equipment.get('cost', {})
            cost_str = f"{cost.get('quantity', 'N/A')} {cost.get('unit', '')}" if isinstance(cost, dict) else 'N/A'

            details_str = ' | '.join(details) if details else 'See details'

            formatted_results.append(
                f"{i}. {name} (Score: {equipment.get('search_score', 0):.3f})\n"
                f"   Category: {category}\n"
                f"   {details_str}\n"
                f"   Weight: {weight} lb | Cost: {cost_str}"
            )

        return "\n\n".join(formatted_results)


class ClassVectorSearchTool(BaseTool):
    """Tool for searching D&D 5E classes using vector similarity"""

    name: str = "Search D&D 5E Classes"
    description: str = (
        "Search for D&D 5E classes and their features using natural language queries. "
        "Use this to find class abilities, proficiencies, hit dice, and level progression. "
        "Examples: 'Find spellcasting classes', 'classes with rage', 'martial classes', 'classes with healing abilities'"
    )
    args_schema: type[BaseModel] = VectorSearchInput

    def _run(self, query: str, limit: int = 5) -> str:
        """Execute class vector search"""
        searcher = MongoDBVectorSearch(database="5e-database")
        results = searcher.search_collection("classes", query, limit=limit)

        if not results:
            return "No classes found matching your query."

        # Format results
        formatted_results = []
        for i, cls in enumerate(results, 1):
            name = cls.get('name', 'Unknown')
            hit_die = cls.get('hit_die', 'N/A')

            # Get proficiencies
            proficiencies = cls.get('proficiencies', [])
            prof_names = [p.get('name', '') for p in proficiencies if isinstance(p, dict)][:3]  # First 3
            prof_str = ', '.join(prof_names) if prof_names else 'N/A'

            # Get spellcasting info
            spellcasting = cls.get('spellcasting', {})
            spellcaster = "Yes" if spellcasting else "No"

            formatted_results.append(
                f"{i}. {name} (Score: {cls.get('search_score', 0):.3f})\n"
                f"   Hit Die: d{hit_die}\n"
                f"   Spellcaster: {spellcaster}\n"
                f"   Proficiencies: {prof_str}"
            )

        return "\n\n".join(formatted_results)


class ConditionVectorSearchTool(BaseTool):
    """Tool for searching D&D 5E conditions using vector similarity"""

    name: str = "Search D&D 5E Conditions"
    description: str = (
        "Search for D&D 5E status conditions (blinded, charmed, stunned, etc.) using natural language. "
        "Use this to find condition effects, limitations, and game mechanics. "
        "Examples: 'Find conditions that prevent movement', 'conditions affecting attack rolls', 'charm effects'"
    )
    args_schema: type[BaseModel] = VectorSearchInput

    def _run(self, query: str, limit: int = 5) -> str:
        """Execute condition vector search"""
        searcher = MongoDBVectorSearch(database="5e-database")
        results = searcher.search_collection("conditions", query, limit=limit)

        if not results:
            return "No conditions found matching your query."

        # Format results
        formatted_results = []
        for i, condition in enumerate(results, 1):
            name = condition.get('name', 'Unknown')
            desc = condition.get('desc', [])

            # Format description (list of strings)
            if isinstance(desc, list):
                desc_text = ' '.join(desc)
            else:
                desc_text = str(desc)

            # Truncate if too long
            if len(desc_text) > 250:
                desc_text = desc_text[:250] + "..."

            formatted_results.append(
                f"{i}. {name} (Score: {condition.get('search_score', 0):.3f})\n"
                f"   Effects: {desc_text}"
            )

        return "\n\n".join(formatted_results)


class MagicItemVectorSearchTool(BaseTool):
    """Tool for searching D&D 5E magic items using vector similarity"""

    name: str = "Search D&D 5E Magic Items"
    description: str = (
        "Search for D&D 5E magic items using natural language queries. "
        "Use this to find magic item properties, rarity, attunement requirements, and effects. "
        "Examples: 'Find legendary magic items', 'items that boost strength', 'wondrous items', 'items requiring attunement'"
    )
    args_schema: type[BaseModel] = VectorSearchInput

    def _run(self, query: str, limit: int = 5) -> str:
        """Execute magic item vector search"""
        searcher = MongoDBVectorSearch(database="5e-database")
        results = searcher.search_collection("magic_items", query, limit=limit)

        if not results:
            return "No magic items found matching your query."

        # Format results
        formatted_results = []
        for i, item in enumerate(results, 1):
            name = item.get('name', 'Unknown')

            # Get rarity
            rarity = item.get('rarity', {})
            rarity_str = rarity.get('name', 'N/A') if isinstance(rarity, dict) else 'N/A'

            # Get description
            desc = item.get('desc', [])
            if isinstance(desc, list):
                desc_text = ' '.join(desc)[:200] + "..."
            else:
                desc_text = str(desc)[:200] + "..."

            formatted_results.append(
                f"{i}. {name} (Score: {item.get('search_score', 0):.3f})\n"
                f"   Rarity: {rarity_str}\n"
                f"   {desc_text}"
            )

        return "\n\n".join(formatted_results)


# Export all tools
__all__ = [
    "MongoDBVectorSearchConfig",
    "EmbeddingGenerator",
    "MongoDBVectorSearch",
    "NPCVectorSearchTool",
    "VenueVectorSearchTool",
    "StageVectorSearchTool",
    "UniversalVectorSearchTool",
    "GameStateSearchTool",
    "MonsterVectorSearchTool",
    "SpellVectorSearchTool",
    "RuleVectorSearchTool",
    "EquipmentVectorSearchTool",
    "ClassVectorSearchTool",
    "ConditionVectorSearchTool",
    "MagicItemVectorSearchTool"
]
