"""
Unified Vector Search Setup for Multiple MongoDB Databases
Supports both campaign and 5e-database with automatic field detection

Usage:
    Configure the constants below, then run:
    python scripts/setup_vector_search_unified.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pymongo import MongoClient
from sentence_transformers import SentenceTransformer
from typing import Dict, List, Any, Set
import time
import json


# ============================================================================
# CONFIGURATION - Edit these constants to customize behavior
# ============================================================================

# Which databases to setup (options: "campaign", "5e-database", or both)
DATABASES_TO_SETUP = ["campaign", "5e-database"]  # Change this to ["campaign"] or ["5e-database"] for single database

# Regenerate embeddings for documents that already have them
FORCE_REGENERATE = False  # Set to True to regenerate all embeddings (slower)

# Attempt to create vector search indexes automatically
# (Will fall back to manual instructions for local MongoDB)
AUTO_CREATE_INDEXES = True  # Set to False to skip automatic index creation

# ============================================================================


class UnifiedVectorSearchSetup:
    """Unified setup for multiple databases"""

    # Configuration
    MONGO_URI = "mongodb://127.0.0.1:27017/?directConnection=true&serverSelectionTimeoutMS=2000"
    EMBEDDING_MODEL_NAME = "all-mpnet-base-v2"
    EMBEDDING_DIMENSIONS = 768
    VECTOR_FIELD = "embedding_vector"

    # Fields to exclude from embeddings
    EXCLUDED_FIELDS = {'_id', 'url', 'updated_at', 'index', 'image'}

    def __init__(self):
        self.client = MongoClient(self.MONGO_URI)
        self.embedding_model = None
        self.database_configs = {}

    def load_embedding_model(self):
        """Load the embedding model once"""
        if self.embedding_model is None:
            print(f"Loading embedding model: {self.EMBEDDING_MODEL_NAME}")
            self.embedding_model = SentenceTransformer(self.EMBEDDING_MODEL_NAME)
            print(f"Model loaded. Embedding dimension: {self.EMBEDDING_DIMENSIONS}\n")

    def detect_text_fields(self, db_name: str, collection_name: str) -> List[str]:
        """
        Auto-detect text fields in a collection by sampling documents
        Excludes: _id, url, updated_at, index, image
        """
        db = self.client[db_name]
        collection = db[collection_name]

        # Sample multiple documents to get all possible fields
        samples = list(collection.find().limit(10))

        if not samples:
            return []

        text_fields = set()

        for sample in samples:
            for field, value in sample.items():
                # Skip excluded fields
                if field in self.EXCLUDED_FIELDS:
                    continue

                # Include string fields with content
                if isinstance(value, str) and len(value.strip()) > 0:
                    text_fields.add(field)

                # Include lists that contain strings
                elif isinstance(value, list) and len(value) > 0:
                    if any(isinstance(item, str) and len(item.strip()) > 0 for item in value):
                        text_fields.add(field)

        return sorted(list(text_fields))

    def scan_database(self, db_name: str) -> Dict[str, Any]:
        """
        Scan a database and detect all collections with their text fields
        """
        print(f"\n{'='*60}")
        print(f"Scanning Database: {db_name}")
        print(f"{'='*60}")

        db = self.client[db_name]
        collections = db.list_collection_names()

        config = {
            'database': db_name,
            'collections': {}
        }

        for coll_name in collections:
            count = db[coll_name].count_documents({})

            if count == 0:
                continue

            # Detect text fields
            text_fields = self.detect_text_fields(db_name, coll_name)

            if text_fields:
                config['collections'][coll_name] = {
                    'count': count,
                    'fields': text_fields
                }
                print(f"\n✓ {coll_name} ({count} documents)")
                print(f"  Text fields ({len(text_fields)}): {text_fields}")

        return config

    def generate_embedding(self, document: Dict[str, Any], fields: List[str]) -> List[float]:
        """Generate embedding for a document by concatenating specified fields"""
        text_parts = []

        for field in fields:
            value = document.get(field)
            if not value:
                continue

            if isinstance(value, str):
                text_parts.append(value)
            elif isinstance(value, list):
                # Handle lists of strings
                for item in value:
                    if isinstance(item, str):
                        text_parts.append(item)
                    elif isinstance(item, dict):
                        text_parts.append(str(item))
            elif isinstance(value, dict):
                text_parts.append(str(value))

        combined_text = " ".join(text_parts)
        return self.embedding_model.encode(combined_text, convert_to_numpy=True).tolist()

    def populate_embeddings(self, db_name: str, collection_name: str, fields: List[str], force_regenerate: bool = False) -> int:
        """Generate and store embeddings for a collection"""
        db = self.client[db_name]
        collection = db[collection_name]

        # Find documents to process
        if force_regenerate:
            documents = list(collection.find({}))
        else:
            documents = list(collection.find({self.VECTOR_FIELD: {"$exists": False}}))

        if not documents:
            return 0

        print(f"\n  Processing {len(documents)} documents...")

        updated_count = 0
        for i, doc in enumerate(documents, 1):
            try:
                embedding = self.generate_embedding(doc, fields)

                collection.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {self.VECTOR_FIELD: embedding}}
                )

                updated_count += 1
                if i % 10 == 0 or i == len(documents):
                    print(f"    [{i}/{len(documents)}] Processed", end='\r')

            except Exception as e:
                print(f"\n  ✗ Error processing document {doc.get('name', doc['_id'])}: {e}")

        print(f"\n  ✓ Successfully added embeddings to {updated_count}/{len(documents)} documents")
        return updated_count

    def create_vector_index(self, db_name: str, collection_name: str) -> bool:
        """
        Create vector search index using pymongo
        Returns True if successful, False if not supported
        """
        db = self.client[db_name]
        collection = db[collection_name]
        index_name = f"vector_index_{collection_name}_mpnet_base_v2_{self.EMBEDDING_DIMENSIONS}"

        try:
            # Try to create search index (MongoDB Atlas only)
            index_definition = {
                "definition": {
                    "mappings": {
                        "dynamic": False,
                        "fields": {
                            self.VECTOR_FIELD: {
                                "type": "vector",
                                "path": self.VECTOR_FIELD,
                                "numDimensions": self.EMBEDDING_DIMENSIONS,
                                "similarity": "dotProduct"
                            }
                        }
                    }
                },
                "name": index_name
            }

            collection.create_search_index(index_definition)
            print(f"  ✓ Vector search index created: {index_name}")
            return True

        except Exception as e:
            error_msg = str(e).lower()
            if "not supported" in error_msg or "atlas" in error_msg or "command" in error_msg:
                return False  # Local MongoDB - needs manual index creation
            else:
                print(f"  ✗ Error creating index: {e}")
                return False

    def generate_index_definition(self, collection_name: str) -> str:
        """Generate MongoDB search index definition for manual creation"""
        index_name = f"vector_index_{collection_name.replace('-', '_')}_mpnet_base_v2_{self.EMBEDDING_DIMENSIONS}"

        # Use getCollection() for collection names with special characters
        return f"""
db.getCollection("{collection_name}").createSearchIndex(
  "{index_name}",
  {{
    mappings: {{
      dynamic: false,
      fields: {{
        {self.VECTOR_FIELD}: {{
          type: "knnVector",
          dimensions: {self.EMBEDDING_DIMENSIONS},
          similarity: "dotProduct"
        }}
      }}
    }}
  }}
);
"""

    def setup_database(self, db_name: str, force_regenerate: bool = False, create_indexes: bool = True):
        """Setup vector search for entire database"""
        # Scan database
        config = self.scan_database(db_name)

        if not config['collections']:
            print(f"\n⚠ No collections with text fields found in {db_name}")
            return

        # Show summary
        print(f"\n{'='*60}")
        print(f"Summary for {db_name}")
        print(f"{'='*60}")
        print(f"Collections: {len(config['collections'])}")
        print(f"Total documents: {sum(c['count'] for c in config['collections'].values())}")

        # Store config
        self.database_configs[db_name] = config

        # Process each collection
        print(f"\n{'='*60}")
        print(f"Generating Embeddings for {db_name}")
        print(f"{'='*60}")

        for coll_name, coll_config in config['collections'].items():
            print(f"\n{coll_name} ({coll_config['count']} documents):")

            self.populate_embeddings(
                db_name,
                coll_name,
                coll_config['fields'],
                force_regenerate
            )

        # Try to create vector search indexes
        if create_indexes:
            print(f"\n{'='*60}")
            print(f"Creating Vector Search Indexes for {db_name}")
            print(f"{'='*60}")

            indexes_created = False
            for coll_name in config['collections'].keys():
                print(f"\n{coll_name}:")
                success = self.create_vector_index(db_name, coll_name)
                if success:
                    indexes_created = True

            if not indexes_created:
                config['needs_manual_indexes'] = True
            else:
                config['needs_manual_indexes'] = False

    def verify_setup(self):
        """Verify embeddings across all databases"""
        print(f"\n{'='*60}")
        print("VERIFICATION RESULTS")
        print(f"{'='*60}")

        for db_name, config in self.database_configs.items():
            print(f"\n{db_name.upper()}:")
            db = self.client[db_name]

            for coll_name, coll_config in config['collections'].items():
                collection = db[coll_name]
                total = collection.count_documents({})
                with_embeddings = collection.count_documents({self.VECTOR_FIELD: {"$exists": True}})

                coverage = f"{(with_embeddings/total*100):.1f}%" if total > 0 else "0%"
                print(f"  {coll_name}: {with_embeddings}/{total} ({coverage})")

    def generate_manual_index_commands(self):
        """Generate manual index creation commands for collections that need them"""
        needs_manual = any(
            config.get('needs_manual_indexes', False)
            for config in self.database_configs.values()
        )

        if not needs_manual:
            return  # All indexes created automatically

        print(f"\n{'='*60}")
        print("MANUAL INDEX CREATION REQUIRED")
        print(f"{'='*60}")
        print("\n⚠ Local MongoDB detected - indexes must be created manually")
        print("\nOption 1: Use MongoDB Compass (Recommended)")
        print("  1. Open Compass → Connect to mongodb://127.0.0.1:27017/")
        print("  2. For each collection below:")
        print("     - Go to collection → Search Indexes tab")
        print("     - Create Search Index → JSON Editor")
        print("     - Use the definition shown below")

        print("\nOption 2: Use mongosh:")
        print("  Copy and run these commands:\n")

        for db_name, config in self.database_configs.items():
            if config.get('needs_manual_indexes', False):
                print(f"\n// Database: {db_name}")
                print(f"use {db_name};")

                for coll_name in config['collections'].keys():
                    print(self.generate_index_definition(coll_name))

    def save_configurations(self):
        """Save configurations to file"""
        output = {
            'model': self.EMBEDDING_MODEL_NAME,
            'dimensions': self.EMBEDDING_DIMENSIONS,
            'databases': self.database_configs
        }

        filename = "vector_search_config_all.json"
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2)

        print(f"\n✓ Configuration saved to: {filename}")

    def run_setup(self, databases: List[str], force_regenerate: bool = False, create_indexes: bool = True):
        """Run complete setup for multiple databases"""
        print("="*60)
        print("UNIFIED VECTOR SEARCH SETUP")
        print("="*60)
        print(f"Databases: {', '.join(databases)}")
        print(f"Model: {self.EMBEDDING_MODEL_NAME}")
        print(f"Dimensions: {self.EMBEDDING_DIMENSIONS}")
        print(f"Excluded fields: {self.EXCLUDED_FIELDS}")
        print(f"Auto-create indexes: {'Yes (will try)' if create_indexes else 'No'}")
        print("="*60)

        # Load model once
        self.load_embedding_model()

        # Setup each database
        for db_name in databases:
            self.setup_database(db_name, force_regenerate, create_indexes)
            time.sleep(0.5)

        # Verify
        self.verify_setup()

        # Generate manual index commands only if needed
        self.generate_manual_index_commands()

        # Save configs
        self.save_configurations()

        print(f"\n{'='*60}")
        print("SETUP COMPLETE!")
        print(f"{'='*60}")

        # Check if any database needs manual indexes
        needs_manual = any(
            config.get('needs_manual_indexes', False)
            for config in self.database_configs.values()
        )

        if needs_manual:
            print("\n⚠ IMPORTANT: Create vector search indexes manually (see commands above)")
        else:
            print("\n✓ All vector search indexes created successfully!")

        print("\nNext steps:")
        print("1. Test vector search:")
        print("   python scripts/test_vector_search.py")
        print("2. Use in your crews - import the tools:")
        print("   from dnd_mas_host.tools.mongodb_vector_tools import NPCVectorSearchTool")
        print("="*60)


def main():
    """Main execution - uses constants defined at top of file"""
    print("\n" + "="*60)
    print("MongoDB Vector Search - Unified Setup")
    print("="*60)

    # Display configuration
    print("\nConfiguration:")
    print(f"  Databases: {', '.join(DATABASES_TO_SETUP)}")
    print(f"  Force regenerate: {'Yes' if FORCE_REGENERATE else 'No (only new documents)'}")
    print(f"  Auto-create indexes: {'Yes (will try)' if AUTO_CREATE_INDEXES else 'No'}")
    print("="*60)

    # Validate configuration
    valid_databases = ["campaign", "5e-database"]
    for db in DATABASES_TO_SETUP:
        if db not in valid_databases:
            print(f"\n✗ Error: Invalid database '{db}'")
            print(f"  Valid options: {', '.join(valid_databases)}")
            return

    if not DATABASES_TO_SETUP:
        print("\n✗ Error: DATABASES_TO_SETUP is empty. Please configure at least one database.")
        return

    # Run setup with configured constants
    setup = UnifiedVectorSearchSetup()
    setup.run_setup(
        databases=DATABASES_TO_SETUP,
        force_regenerate=FORCE_REGENERATE,
        create_indexes=AUTO_CREATE_INDEXES
    )


if __name__ == "__main__":
    main()
