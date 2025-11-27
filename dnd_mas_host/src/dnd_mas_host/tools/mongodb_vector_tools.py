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
    DATABASE_NAME = "campaign"  # Changed from "dnd_game" to match your actual database

    # Collections
    COLLECTIONS = {
        "npcs": "npcs",
        "venues": "venues",
        "stages": "stages",
        "stories": "stories"
    }

    # Embedding Model Configuration
    # Using all-mpnet-base-v2: 768 dimensions, high quality local model
    EMBEDDING_MODEL_NAME = "all-mpnet-base-v2"
    EMBEDDING_DIMENSIONS = 768

    # Vector Index Names (including model and dimension info)
    VECTOR_INDEX_NAMES = {
        "npcs": f"vector_index_npcs_mpnet_base_v2_{EMBEDDING_DIMENSIONS}",
        "venues": f"vector_index_venues_mpnet_base_v2_{EMBEDDING_DIMENSIONS}",
        "stages": f"vector_index_stages_mpnet_base_v2_{EMBEDDING_DIMENSIONS}",
        "stories": f"vector_index_stories_mpnet_base_v2_{EMBEDDING_DIMENSIONS}"
    }

    # Fields to embed for each collection
    EMBEDDING_FIELDS = {
        "npcs": ["name", "desc", "personality", "intention", "target"],
        "venues": ["name", "envDesc", "storyDesc"],
        "stages": ["name", "envDesc", "storyDesc", "startNarrative"],
        "stories": ["name", "startNarrative", "objective", "outline", "mapDesc"]
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

    def __init__(self):
        self.client = MongoClient(MongoDBVectorSearchConfig.MONGO_URI)
        self.db = self.client[MongoDBVectorSearchConfig.DATABASE_NAME]
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
        collection = self.db[MongoDBVectorSearchConfig.COLLECTIONS[collection_name]]
        index_name = MongoDBVectorSearchConfig.VECTOR_INDEX_NAMES[collection_name]

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

        for collection_name in MongoDBVectorSearchConfig.COLLECTIONS.keys():
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


# Export all tools
__all__ = [
    "MongoDBVectorSearchConfig",
    "EmbeddingGenerator",
    "MongoDBVectorSearch",
    "NPCVectorSearchTool",
    "VenueVectorSearchTool",
    "StageVectorSearchTool",
    "UniversalVectorSearchTool"
]
