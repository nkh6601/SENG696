# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Dungeons & Dragons 5E multi-agent system (MAS) powered by CrewAI. The system orchestrates multiple AI agents that work together to create an interactive D&D experience, including a Narrator, NPCs, and a Judge to manage gameplay mechanics.

**Campaign**: "Humantown: Rescue from the Town of Slimes" - information exist in the MongoDB

### System Goals
This text-based, AI-generated interactive story system aims to:
1. **Dynamic Story Generation**: Generate narratives based on user prompts and story progress
2. **Interactive Control**: Allow players to control main character actions
3. **Rule Adherence**: Ensure all actions and stories align with D&D 5E 2014 game rules
4. **Avoid Invalid Input Confusion**: Validate and clarify ambiguous/invalid user prompts
5. **Maintain Consistency**: Prevent inconsistencies in AI-generated content using RAG and structured data
6. **Proactive NPCs**: Enable reactive behaviors from NPCs, environment, and storyline events

The system replaces the traditional Game Master role (narrative/storytelling, rule adjudication, NPC management, world-building) with specialized AI agents.

## Architecture

### V2 Architecture: Message-Passing with Blackboard Pattern

The system now uses a FIPA-inspired message-passing architecture with centralized Blackboard pattern:

**Entry Point**: `python -m dnd_mas_host.interface` (launches InterfaceAgentV2)

**Core Components**:

1. **HostManager** ([manager/host_manager.py](src/dnd_mas_host/manager/host_manager.py)) - System Backbone
   - Owns unified message queue
   - Routes ALL messages to appropriate agents
   - Kicks off agent execution (NarratorFlow, JudgeFlow)
   - Manages NPC crews (REUSE existing, CREATE new, DELETE inactive)
   - Owns BlackboardManager instance

2. **BlackboardManager** ([state/blackboard_manager.py](src/dnd_mas_host/state/blackboard_manager.py))
   - Centralized HostState access
   - Read/write with configurable logging (`ENABLE_BLACKBOARD_LOGGING` in config.py)
   - Reset turn state between prompts
   - NPC crew lifecycle management

3. **HostState** ([state/host_state.py](src/dnd_mas_host/state/host_state.py)) - Nested Structure
   - `workflow`: WorkflowState (step tracking, error handling)
   - `game_context`: GameContext (campaign, characters, venues - immutable)
   - `current_turn`: TurnState (prompt, action, consequences, reactions)
   - `output`: OutputState (narratives, previous context)

4. **Message Types** ([interface/message_types.py](src/dnd_mas_host/interface/message_types.py))
   - Agent-to-agent: VALIDATE_PROMPT, CHECK_FEASIBILITY, EVALUATE_CONSEQUENCE, etc.
   - Interface messages: REQUEST_DIFFICULTY_CHECK, DISPLAY_NARRATIVE, VALIDATION_ERROR
   - Error handling: FLOW_ERROR

**Message Flow**:
```
User Prompt → Interface → VALIDATE_PROMPT → Narrator → CHECK_FEASIBILITY → Judge
                ↓                                              ↓
        VALIDATION_ERROR (if invalid)                REQUEST_DIFFICULTY_CHECK
                                                              ↓
                                                    User rolls d20
                                                              ↓
                                              EVALUATE_CONSEQUENCE → Judge
                                                              ↓
                                              EVALUATE_REACTIONS → NPC Processing
                                                              ↓
                                              GENERATE_NARRATIVE → Narrator
                                                              ↓
                                              DISPLAY_NARRATIVE → Interface
```

### MongoDB Vector Search (RAG)
[src/dnd_mas_host/tools/mongodb_vector_tools.py](src/dnd_mas_host/tools/mongodb_vector_tools.py) implements RAG with local embeddings:

**Embedding Model**: `all-mpnet-base-v2` (768 dimensions) via SentenceTransformer

**Databases**:
- `campaign`: Custom game content (npcs, venues, stages, stories)
- `5e-database`: D&D 5E 2014 SRD data from [5e-bits/5e-database](https://github.com/5e-bits/5e-database)

## Important Notes

- **V2 Architecture**: Message-passing with Blackboard pattern (entry point: `python -m dnd_mas_host.interface`)
- **Legacy Architecture**: Flow-based with HostFlow orchestration (entry point: `python -m dnd_mas_host.interface.interface_agent`)
- All game state MUST be tracked in HostState/BlackboardManager (agents have no internal memory)
- If any unclear or question, please ask before proceed with the implementation or planning

## V2 Architecture File Structure

**Key Design Patterns**:
- **Blackboard Pattern**: Centralized HostState accessible to all agents via BlackboardManager
- **Message-Passing**: Agents send domain-specific messages via unified queue
- **NPC Crew Lifecycle**: REUSE existing crews, CREATE new for new characters, DELETE for inactive
- **DEX Ordering**: NPCs processed in dexterity order (high to low)