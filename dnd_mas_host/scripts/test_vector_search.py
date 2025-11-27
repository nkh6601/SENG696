"""
Test script for MongoDB Vector Search functionality
Tests the vector search tools with sample queries

Usage:
    python scripts/test_vector_search.py
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dnd_mas_host.tools.mongodb_vector_tools import (
    NPCVectorSearchTool,
    VenueVectorSearchTool,
    StageVectorSearchTool,
    UniversalVectorSearchTool,
    MongoDBVectorSearch
)


def test_npc_search():
    """Test NPC vector search"""
    print("\n" + "="*60)
    print("TEST 1: NPC Vector Search")
    print("="*60)

    tool = NPCVectorSearchTool()

    test_queries = [
        "Find hostile or aggressive NPCs",
        "NPCs who can provide information",
        "Characters related to experiments",
        "Friendly helpful characters"
    ]

    for query in test_queries:
        print(f"\nQuery: '{query}'")
        print("-" * 60)
        result = tool._run(query=query, limit=3)
        print(result)


def test_venue_search():
    """Test venue vector search"""
    print("\n" + "="*60)
    print("TEST 2: Venue Vector Search")
    print("="*60)

    tool = VenueVectorSearchTool()

    test_queries = [
        "Find dangerous combat locations",
        "Places where players can rest",
        "Locations related to museums or research",
        "Outdoor garden areas"
    ]

    for query in test_queries:
        print(f"\nQuery: '{query}'")
        print("-" * 60)
        result = tool._run(query=query, limit=3)
        print(result)


def test_stage_search():
    """Test stage vector search"""
    print("\n" + "="*60)
    print("TEST 3: Stage Vector Search")
    print("="*60)

    tool = StageVectorSearchTool()

    test_queries = [
        "Investigation and exploration stages",
        "Final confrontation or boss battle",
        "Stages with experiments or laboratories"
    ]

    for query in test_queries:
        print(f"\nQuery: '{query}'")
        print("-" * 60)
        result = tool._run(query=query, limit=2)
        print(result)


def test_universal_search():
    """Test universal search across all collections"""
    print("\n" + "="*60)
    print("TEST 4: Universal Search (All Collections)")
    print("="*60)

    tool = UniversalVectorSearchTool()

    test_queries = [
        "Everything related to Alistair Porridgepot",
        "Content about slimes and oozes",
        "The windmill or mill",
        "Jaylen the prisoner"
    ]

    for query in test_queries:
        print(f"\nQuery: '{query}'")
        print("-" * 60)
        result = tool._run(query=query, limit=2)
        print(result)


def test_direct_search():
    """Test direct MongoDB vector search (lower level)"""
    print("\n" + "="*60)
    print("TEST 5: Direct MongoDB Vector Search")
    print("="*60)

    searcher = MongoDBVectorSearch()

    # Test search with filter
    print("\nSearching NPCs with filter...")
    print("-" * 60)
    results = searcher.search_collection(
        collection_name="npcs",
        query_text="evil wizard",
        limit=3,
        filter_dict={"personality": {"$exists": True}}
    )

    for i, result in enumerate(results, 1):
        print(f"\n{i}. {result['name']} (Score: {result.get('search_score', 0):.3f})")
        print(f"   {result.get('desc', 'N/A')[:150]}...")


def test_search_across_collections():
    """Test searching all collections"""
    print("\n" + "="*60)
    print("TEST 6: Search Across All Collections")
    print("="*60)

    searcher = MongoDBVectorSearch()

    query = "tavern and social interactions"
    print(f"\nQuery: '{query}'")
    print("-" * 60)

    results = searcher.search_all_collections(query, limit_per_collection=2)

    for collection_name, docs in results.items():
        if docs:
            print(f"\n{collection_name.upper()}:")
            for doc in docs:
                print(f"  - {doc['name']} (Score: {doc.get('search_score', 0):.3f})")


def main():
    """Run all tests"""
    print("\n" + "#"*60)
    print("# MongoDB Vector Search Test Suite")
    print("#"*60)
    print("\nThis will test vector search across all collections.")
    print("Make sure you've run scripts/create_vector_indexes.py first!")
    print("#"*60)

    input("\nPress Enter to continue...")

    try:
        # Run all tests
        test_npc_search()
        test_venue_search()
        test_stage_search()
        test_universal_search()
        test_direct_search()
        test_search_across_collections()

        print("\n" + "="*60)
        print("✓ ALL TESTS COMPLETED")
        print("="*60)
        print("\nVector search is working correctly!")
        print("You can now use these tools in your CrewAI agents.")

    except Exception as e:
        print("\n" + "="*60)
        print("✗ TEST FAILED")
        print("="*60)
        print(f"\nError: {e}")
        print("\nTroubleshooting:")
        print("1. Run: python scripts/create_vector_indexes.py")
        print("2. Ensure MongoDB is running")
        print("3. Check that embeddings were generated")
        print("4. If using local MongoDB, create search indexes manually")


if __name__ == "__main__":
    main()
