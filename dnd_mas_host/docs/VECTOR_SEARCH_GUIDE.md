# MongoDB Vector Search & RAG Guide

Complete documentation for MongoDB Vector Search integration with RAG (Retrieval-Augmented Generation) in the DnD Multi-Agent System.

---

## Table of Contents

1. [Overview](#overview)
2. [Quick Start](#quick-start)
3. [Configuration](#configuration)
4. [How It Works](#how-it-works)
5. [Usage in Crews](#usage-in-crews)
6. [Available Tools](#available-tools)
7. [Testing](#testing)
8. [Docker Backup & Restore](#docker-backup--restore)
9. [Troubleshooting](#troubleshooting)
10. [Technical Reference](#technical-reference)

---

## Overview

### What is Vector Search?

Vector search converts text into numerical vectors (embeddings) and finds semantically similar content using mathematical operations instead of keyword matching.

**Example:**
- Query: "hostile characters"
- Finds: NPCs with descriptions like "aggressive guard" or "angry merchant" even without the word "hostile"

### What is RAG?

**R**etrieval-**A**ugmented **G**eneration enables AI agents to:
1. Retrieve relevant context from MongoDB before responding
2. Ground responses in your actual game data
3. Provide accurate, contextual answers

### Benefits

- ✅ Natural language queries (no complex filters needed)
- ✅ Semantic understanding (finds related concepts)
- ✅ Local execution (no API costs, GPU accelerated)
- ✅ Automatic field detection (minimal configuration)
- ✅ Multi-database support (campaign + 5e-database)

---

## Quick Start

### 1. Install Dependencies

**For GPU support (recommended):**
```bash
# Install PyTorch with CUDA first
pip3 install torch torchvision --index-url https://download.pytorch.org/whl/cu130

# Then install other dependencies
pip install -r requirements_vector_search.txt
```

**For CPU only:**
```bash
pip install -r requirements_vector_search.txt
```

### 2. Configure Setup

Edit `scripts/setup_vector_search_unified.py`:

```python
# Which databases to setup
DATABASES_TO_SETUP = ["campaign", "5e-database"]  # Both databases
# DATABASES_TO_SETUP = ["campaign"]  # Only campaign
# DATABASES_TO_SETUP = ["5e-database"]  # Only 5e-database

# Regenerate existing embeddings?
FORCE_REGENERATE = False  # False = only new documents (recommended)

# Attempt automatic index creation?
AUTO_CREATE_INDEXES = True  # True = try automatic (will provide manual commands if needed)
```

### 3. Run Setup

```bash
python scripts/setup_vector_search_unified.py
```

This will:
- ✓ Scan databases and detect text fields
- ✓ Generate 768-dimensional embeddings for all documents
- ✓ Add `embedding_vector` field to each document
- ✓ Attempt automatic index creation (or provide manual commands)

### 4. Create Indexes Manually (if needed)

If using local MongoDB, copy the generated commands and run in mongosh:

```bash
mongosh
```

```javascript
use campaign;

db.getCollection("npcs").createSearchIndex(
  "vector_index_npcs_mpnet_base_v2_768",
  {
    mappings: {
      dynamic: false,
      fields: {
        embedding_vector: {
          type: "knnVector",
          dimensions: 768,
          similarity: "dotProduct"
        }
      }
    }
  }
);

// Repeat for other collections...
```

### 5. Test

```bash
python scripts/test_vector_search.py
```

---

## Configuration

### Database Setup

**Location:** `scripts/setup_vector_search_unified.py`

```python
# Top-level configuration constants
DATABASES_TO_SETUP = ["campaign", "5e-database"]
FORCE_REGENERATE = False
AUTO_CREATE_INDEXES = True
```

### Class Configuration

**Location:** `scripts/setup_vector_search_unified.py`

```python
class UnifiedVectorSearchSetup:
    # MongoDB connection
    MONGO_URI = "mongodb://127.0.0.1:27017/?directConnection=true&serverSelectionTimeoutMS=2000"

    # Embedding model
    EMBEDDING_MODEL_NAME = "all-mpnet-base-v2"  # 768 dimensions, high quality
    EMBEDDING_DIMENSIONS = 768
    VECTOR_FIELD = "embedding_vector"  # Field name in documents

    # Auto-exclude these fields from embeddings
    EXCLUDED_FIELDS = {'_id', 'url', 'updated_at', 'index', 'image'}
```

### Tool Configuration

**Location:** `src/dnd_mas_host/tools/mongodb_vector_tools.py`

```python
class MongoDBVectorSearchConfig:
    MONGO_URI = "mongodb://127.0.0.1:27017/?directConnection=true&serverSelectionTimeoutMS=2000"
    DATABASE_NAME = "campaign"
    EMBEDDING_MODEL_NAME = "all-mpnet-base-v2"
    EMBEDDING_DIMENSIONS = 768
    VECTOR_FIELD = "embedding_vector"

    # Campaign database collections
    COLLECTIONS = {
        "npcs": "npcs",
        "venues": "venues",
        "stages": "stages",
        "stories": "stories"
    }

    # Fields to embed for each collection
    EMBEDDING_FIELDS = {
        "npcs": ["name", "desc", "personality", "intention", "target"],
        "venues": ["name", "envDesc", "storyDesc"],
        "stages": ["name", "envDesc", "storyDesc", "startNarrative"],
        "stories": ["name", "startNarrative", "objective", "outline", "mapDesc"]
    }
```

---

## How It Works

### Architecture

```
┌─────────────────────────────────────┐
│        CrewAI Agents                │
│  (Narrator, NPC, Judge)             │
└──────────────┬──────────────────────┘
               │ Uses tools
               ▼
┌─────────────────────────────────────┐
│    Vector Search Tools              │
│  NPCVectorSearchTool                │
│  VenueVectorSearchTool              │
│  StageVectorSearchTool              │
│  UniversalVectorSearchTool          │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│    Embedding Generator              │
│  Model: all-mpnet-base-v2           │
│  Converts: text → 768-dim vector    │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│    MongoDB Database                 │
│  Collections with embedding_vector  │
└─────────────────────────────────────┘
```

### Workflow

#### Step 1: Generate Embeddings

**Before:**
```json
{
  "_id": ObjectId("..."),
  "name": "Alistair Porridgepot",
  "desc": "Halfling mad alchemist",
  "personality": "Completely insane"
}
```

**After:**
```json
{
  "_id": ObjectId("..."),
  "name": "Alistair Porridgepot",
  "desc": "Halfling mad alchemist",
  "personality": "Completely insane",
  "embedding_vector": [0.123, -0.456, 0.789, ..., 0.234]  // 768 numbers
}
```

**Process:**
1. Concatenate fields: "Alistair Porridgepot Halfling mad alchemist Completely insane"
2. Pass to model: `all-mpnet-base-v2`
3. Get 768-dimensional vector representing semantic meaning
4. Store in `embedding_vector` field

#### Step 2: Create Index

Tell MongoDB to index the `embedding_vector` field for fast similarity search:

```javascript
db.npcs.createSearchIndex(
  "vector_index_npcs_mpnet_base_v2_768",
  {
    mappings: {
      fields: {
        embedding_vector: {  // The field from Step 1
          type: "knnVector",
          dimensions: 768,
          similarity: "dotProduct"
        }
      }
    }
  }
);
```

#### Step 3: Query

When agent searches:
1. Convert query text to vector: "hostile characters" → [0.234, 0.567, ...]
2. MongoDB finds documents with similar vectors using dotProduct
3. Return top K most similar documents
4. Agent uses results to inform response

---

## Usage in Crews

### Import Tools

```python
from dnd_mas_host.tools.mongodb_vector_tools import (
    NPCVectorSearchTool,
    VenueVectorSearchTool,
    StageVectorSearchTool,
    UniversalVectorSearchTool
)
```

### Example: NPC Crew with RAG

```python
from crewai import Agent, Task, Crew

# Create NPC agent with vector search capability
npc_agent = Agent(
    role="NPC Character",
    goal="Play the role of NPCs in the game world",
    backstory="You embody various NPCs, adapting personality based on context",
    tools=[NPCVectorSearchTool()],  # Add RAG tool
    verbose=True
)

# Task that will use the tool
task = Task(
    description="""
    The player asks: "Are there any alchemists nearby?"
    Search for relevant NPCs and respond in character.
    """,
    expected_output="In-character response mentioning found NPCs",
    agent=npc_agent
)

# Agent will automatically use NPCVectorSearchTool to find alchemists
crew = Crew(agents=[npc_agent], tasks=[task])
result = crew.kickoff()
```

### Example: Narrator with Multiple Tools

```python
narrator = Agent(
    role="Game Master Narrator",
    goal="Narrate the game world with rich detail",
    backstory="You describe scenes, locations, and NPCs vividly",
    tools=[
        VenueVectorSearchTool(),  # Search locations
        StageVectorSearchTool(),  # Search story stages
        NPCVectorSearchTool(),    # Search characters
    ],
    verbose=True
)

task = Task(
    description="Describe the current scene at the tavern",
    expected_output="Rich narrative description of the tavern and its occupants",
    agent=narrator
)
```

### Example: Universal Search

```python
judge_agent = Agent(
    role="Game Judge",
    goal="Resolve player actions and enforce rules",
    backstory="You arbitrate conflicts and determine outcomes",
    tools=[UniversalVectorSearchTool()],  # Search all collections
    verbose=True
)

task = Task(
    description="""
    Player casts fireball in the laboratory.
    Find relevant information about the laboratory and any NPCs present.
    Determine the outcome.
    """,
    expected_output="Detailed outcome of the action",
    agent=judge_agent
)
```

---

## Available Tools

### NPCVectorSearchTool

**Purpose:** Search NPCs by semantic similarity

**Input:**
```python
{
    "query": "hostile characters in the tavern",
    "top_k": 3  # Optional, default: 5
}
```

**Output:**
```python
[
    {
        "name": "Tavern Owner",
        "desc": "Grumpy human innkeeper",
        "personality": "Distrustful of strangers",
        "score": 0.89
    },
    # ... more results
]
```

### VenueVectorSearchTool

**Purpose:** Search locations/venues

**Input:**
```python
{
    "query": "dangerous laboratory",
    "top_k": 5
}
```

### StageVectorSearchTool

**Purpose:** Search story stages/scenes

**Input:**
```python
{
    "query": "confrontation with villain",
    "top_k": 3
}
```

### UniversalVectorSearchTool

**Purpose:** Search all collections simultaneously

**Input:**
```python
{
    "query": "everything about slimes",
    "collections": ["npcs", "venues", "stages"],  # Optional
    "top_k": 5
}
```

**Output:**
```python
{
    "npcs": [{"name": "Slime King", "score": 0.92}, ...],
    "venues": [{"name": "Slime Laboratory", "score": 0.87}, ...],
    "stages": [{"name": "Slime Town Invasion", "score": 0.85}, ...]
}
```

---

## Testing

### Run Test Suite

```bash
python scripts/test_vector_search.py
```

### Test Output

```
============================================================
MongoDB Vector Search - Test Suite
============================================================

Configuration:
  Database: campaign
  Model: all-mpnet-base-v2 (768 dims)
  Collections: npcs, venues, stages, stories

------------------------------------------------------------
Test 1: NPC Search - "mad alchemist"
------------------------------------------------------------
✓ Found 3 NPCs
  1. Alistair Porridgepot (score: 0.89)
     Halfling mad alchemist obsessed with creating life
  2. Laboratory Assistant (score: 0.72)
     Nervous human working on experiments
  ...

------------------------------------------------------------
Test 2: Venue Search - "dangerous laboratory"
------------------------------------------------------------
✓ Found 2 venues
  1. Laboratory M3 (score: 0.91)
     Underground lab with unstable experiments
  ...

------------------------------------------------------------
All tests passed!
------------------------------------------------------------
```

### Manual Testing

```python
from dnd_mas_host.tools.mongodb_vector_tools import NPCVectorSearchTool

tool = NPCVectorSearchTool()
result = tool._run(
    query="friendly merchants",
    top_k=3
)
print(result)
```

---

## Docker Backup & Restore

MongoDB is running in Docker containers, making it easy to backup and restore the entire system.

### Docker Setup Overview

**Containers:**
- `mongod-community` - MongoDB server (port 27017)
- `mongot-community-pupr` - MongoDB search (Windows-compatible)

**Volumes:**
- `mongodb3_mongod_data` - Database data
- `mongodb3_mongot_data` - Search indexes

**Location:** `i:/Project/SENG696/mongodb3/`

### Creating a Backup

The backup script creates a complete portable archive including data, configurations, and Docker images.

```powershell
# Navigate to mongodb3 directory
cd i:/Project/SENG696/mongodb3

# Run backup script
.\backup.ps1
```

**What's included in backup:**
- ✓ All MongoDB data (campaign + 5e-database)
- ✓ Vector embeddings (768-dim vectors)
- ✓ Search indexes
- ✓ Configuration files
- ✓ Docker images (Windows-compatible)
- ✓ Auto-restore script

**Output:** `mongodb-complete-YYYYMMDD_HHMMSS.zip` (typically 1-2GB)

**What happens during backup:**
1. Containers stop temporarily
2. Data volumes exported to tar.gz files
3. Configuration files copied
4. Docker images saved (including Windows modifications)
5. RESTORE.ps1 script generated
6. Everything compressed to ZIP
7. Containers restart automatically

### Restoring from Backup

Restore on any machine with Docker Desktop installed.

```powershell
# 1. Extract backup ZIP
Expand-Archive -Path mongodb-complete-20251126_143045.zip -DestinationPath .

# 2. Navigate to extracted folder
cd mongodb-complete-20251126_143045

# 3. Run auto-restore script
.\RESTORE.ps1

# 4. Verify containers running
docker ps
```

**What happens during restore:**
1. Checks Docker is running
2. Warns if existing volumes found (option to overwrite)
3. Creates search-community network (if needed)
4. Loads Docker images from tar files
5. Creates volumes and restores data
6. Starts containers
7. Verifies MongoDB connection

**After restore:**
- MongoDB accessible at: `mongodb://127.0.0.1:27017/`
- Databases: `campaign` and `5e-database`
- All vector embeddings preserved
- Search indexes functional

### Docker Operations

**Start services:**
```powershell
cd i:/Project/SENG696/mongodb3
docker-compose up -d
```

**Stop services:**
```powershell
docker-compose stop
```

**View logs:**
```powershell
# All logs
docker-compose logs -f

# MongoDB only
docker-compose logs -f mongod
```

**Access MongoDB shell:**
```powershell
docker exec -it mongod-community mongosh
```

**Check container status:**
```powershell
docker ps
```

### Backup Best Practices

**When to backup:**
- Before major changes to data
- After adding new vector embeddings
- Before system upgrades
- Regularly (weekly/monthly)

**Storage:**
- Keep backups on external drive
- Store in cloud storage (OneDrive, Google Drive)
- Maintain at least 2 recent backups

**Verification:**
- Test restore process periodically
- Verify ZIP file integrity
- Check backup file size (should be 1-2GB)

### Docker Troubleshooting

**Containers won't start:**
```powershell
# Check logs
docker-compose logs

# Check if port 27017 is in use
netstat -ano | findstr :27017

# Restart Docker Desktop, then:
docker-compose up -d
```

**Backup script fails:**
```powershell
# Ensure containers are running first
docker-compose up -d

# Check disk space
docker system df

# Try running as administrator
```

**Restore fails:**
```powershell
# Remove existing volumes first
docker volume rm mongodb3_mongod_data mongodb3_mongot_data

# Ensure search-community network exists
docker network create search-community

# Re-run RESTORE.ps1
```

For more Docker operations, see: `i:/Project/SENG696/mongodb3/README.md`

---

## Troubleshooting

### Common Issues

#### 1. No results found

**Problem:** Query returns empty results

**Solutions:**
- Verify embeddings exist: Check MongoDB for `embedding_vector` field
- Verify indexes created: Check "Search Indexes" tab in MongoDB Compass
- Check collection name: Ensure spelling matches exactly
- Try broader query: "alchemist" instead of "mad scientist alchemist with potions"

**Verify embeddings:**
```python
from pymongo import MongoClient
client = MongoClient("mongodb://127.0.0.1:27017/")
db = client["campaign"]
count = db.npcs.count_documents({"embedding_vector": {"$exists": True}})
print(f"Documents with embeddings: {count}")
```

#### 2. Index creation fails

**Problem:** `SyntaxError` or "command not supported"

**Solutions:**
- **Local MongoDB:** Must create indexes manually (not supported via pymongo)
- **Collection names with special characters:** Use `db.getCollection("name")` syntax
- **Wrong mongosh version:** Update to latest: `npm install -g mongosh`

**Verify indexes:**
```javascript
// In mongosh
use campaign;
db.npcs.getSearchIndexes();
```

#### 3. Slow performance

**Problem:** Queries take too long

**Solutions:**
- Use GPU acceleration: Install PyTorch with CUDA
- Reduce `top_k`: Query fewer results (e.g., 3 instead of 10)
- Check index exists: Index dramatically speeds up search
- Check hardware: CPU-only is slower but still functional

**Enable GPU:**
```bash
pip3 install torch torchvision --index-url https://download.pytorch.org/whl/cu130
```

#### 4. PyTorch version conflicts

**Problem:** `RuntimeError: operator torchvision::nms does not exist`

**Solution:**
```bash
# Uninstall existing
pip uninstall torch torchvision

# Install GPU version
pip3 install torch torchvision --index-url https://download.pytorch.org/whl/cu130

# Then install requirements
pip install -r requirements_vector_search.txt
```

#### 5. Out of memory

**Problem:** CUDA out of memory or system RAM exhausted

**Solutions:**
- Process in smaller batches: Modify script to process fewer documents at once
- Use CPU: Set `device='cpu'` in embedding generation
- Close other applications
- Reduce batch size in `populate_embeddings()`

---

## Technical Reference

### Embedding Model

**Model:** `all-mpnet-base-v2`
- **Dimensions:** 768
- **Performance:** High quality semantic understanding
- **Speed:** ~100 docs/sec on GPU, ~10 docs/sec on CPU
- **Size:** ~420MB download
- **Source:** Sentence Transformers library

**Why this model?**
- Best quality for local execution
- Good balance of speed and accuracy
- Widely tested and reliable
- No API costs

### Similarity Metric

**Method:** `dotProduct`
- Measures vector similarity via dot product
- Range: -1 (opposite) to +1 (identical)
- Fast computation
- Equivalent to cosine similarity for normalized vectors

### Index Type

**Type:** `knnVector` (k-nearest neighbors)
- Finds K most similar vectors
- Uses approximate nearest neighbor search (fast)
- MongoDB Atlas uses HNSW algorithm internally
- Local MongoDB requires manual index creation

### Collections

#### Campaign Database

| Collection | Text Fields | Purpose |
|------------|-------------|---------|
| `npcs` | name, desc, personality, intention, target | Non-player characters |
| `venues` | name, envDesc, storyDesc | Locations |
| `stages` | name, envDesc, storyDesc, startNarrative | Story stages |
| `stories` | name, startNarrative, objective, outline, mapDesc | Story arcs |

#### 5E-Database

Automatically detects all text fields in D&D 5E SRD collections (classes, spells, monsters, etc.)

**Excluded fields:** `_id`, `url`, `updated_at`, `index`, `image`

### File Structure

```
dnd_mas_host/
├── src/dnd_mas_host/tools/
│   └── mongodb_vector_tools.py        # RAG tools for CrewAI
├── scripts/
│   ├── setup_vector_search_unified.py # Main setup script
│   ├── test_vector_search.py          # Test suite
│   ├── check_campaign_db.py           # Database inspection
│   ├── debug_mongodb_connection.py    # Connection debugging
│   └── explore_5e_database.py         # 5e-database exploration
├── docs/
│   └── VECTOR_SEARCH_GUIDE.md         # This file
├── requirements_vector_search.txt      # Dependencies
└── vector_search_config_all.json      # Generated configuration
```

### Dependencies

```
pymongo>=4.6.0              # MongoDB driver
sentence-transformers>=3.0.0 # Embedding models
transformers>=4.30.0        # Transformers library
numpy>=1.24.0               # Array operations
torch>=2.6.0                # PyTorch
torchvision>=0.19.0         # Vision utilities
pillow>=9.0.0               # Image processing
tqdm>=4.65.0                # Progress bars
```

### MongoDB Connection String

```
mongodb://127.0.0.1:27017/?directConnection=true&serverSelectionTimeoutMS=2000
```

**Parameters:**
- `directConnection=true`: Connect directly to server (no replica set)
- `serverSelectionTimeoutMS=2000`: 2 second timeout
- Port: `27017` (default MongoDB port)
- Host: `127.0.0.1` (localhost)

---

## Advanced Topics

### Adding New Collections

1. Add to configuration in `mongodb_vector_tools.py`:
```python
COLLECTIONS = {
    "npcs": "npcs",
    "venues": "venues",
    "my_new_collection": "my_new_collection"  # Add here
}

EMBEDDING_FIELDS = {
    # ... existing fields ...
    "my_new_collection": ["field1", "field2", "field3"]  # Specify fields
}
```

2. Re-run setup:
```bash
python scripts/setup_vector_search_unified.py
```

### Changing Embedding Model

Edit `setup_vector_search_unified.py`:

```python
class UnifiedVectorSearchSetup:
    EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"  # Faster, smaller (384 dims)
    EMBEDDING_DIMENSIONS = 384  # Match model dimensions
```

**Popular alternatives:**
- `all-MiniLM-L6-v2`: 384 dims, faster, lower quality
- `all-mpnet-base-v2`: 768 dims, balanced (default)
- `sentence-t5-xl`: 768 dims, highest quality, slowest

### Custom Queries

```python
from dnd_mas_host.tools.mongodb_vector_tools import MongoDBVectorSearch

searcher = MongoDBVectorSearch()

# Custom query with filters
results = searcher.search(
    collection_name="npcs",
    query="friendly merchant",
    top_k=10,
    filter={"location": "tavern"}  # Additional filter
)
```

### Batch Processing

For large datasets, process in batches:

```python
# In setup_vector_search_unified.py, modify populate_embeddings():

batch_size = 100
for i in range(0, len(documents), batch_size):
    batch = documents[i:i+batch_size]
    for doc in batch:
        # Process document
        pass
```

---

## Support

### Getting Help

1. Check [Troubleshooting](#troubleshooting) section
2. Review error messages carefully
3. Verify configuration constants
4. Test with simple queries first
5. Check MongoDB connection and data

### Useful Commands

**Check MongoDB connection:**
```bash
python scripts/debug_mongodb_connection.py
```

**Inspect database:**
```bash
python scripts/check_campaign_db.py
```

**Test specific collection:**
```bash
python scripts/test_vector_search.py
```

**View indexes in mongosh:**
```javascript
use campaign;
db.npcs.getSearchIndexes();
```

---

## Next Steps

1. ✅ **Complete setup** - Run unified setup script
2. ✅ **Create indexes** - Manual creation if local MongoDB
3. ✅ **Run tests** - Verify everything works
4. ✅ **Integrate with crews** - Add tools to your agents
5. ✅ **Test in game** - Use in actual gameplay scenarios
6. ✅ **Monitor performance** - Check query speeds and accuracy
7. ✅ **Iterate** - Refine queries and configurations as needed

---

**Last Updated:** 2025-11-26
**Version:** 1.0
**Model:** all-mpnet-base-v2 (768 dimensions)
