# Hierarchical Judge Agent: Implementation Plan

## Executive Summary

This document provides both the **analysis** and **detailed implementation plan** for refactoring the Judge agent from a monolithic structure to a hierarchical multi-agent system.

**Current State**: 1 agent, 3 sequential tasks (all execute every time, ~61% token waste)
**Proposed State**: 3 specialized crews with conditional execution via Python manager

**Key Benefits**:
- **50-61% token reduction** through conditional crew execution
- **Early rejection** of invalid actions (skip DC evaluation)
- **Clear separation of concerns** (feasibility, difficulty, consequences)
- **Backward compatible** via feature flag

**Implementation Estimate**: 4-6 weeks (design → development → testing → rollout → cleanup)

---

## Current Judge Architecture (Baseline)

### Structure
- **Single Agent**: One "judge" agent handles all responsibilities
- **Three Tasks** (always execute sequentially):
  1. `check_difficulty` - Assigns DC (Difficulty Class) for action
  2. `good_action_result` - Evaluates success consequences
  3. `bad_action_result` - Evaluates failure consequences
- **Process**: `Process.sequential` (one agent, sequential tasks)

### Current Pain Points
1. **Token Waste**: All 3 tasks execute on every kickoff
   - First call (difficulty evaluation): Only needs Task 0, wastes Tasks 1 & 2
   - Second call (consequence evaluation): Only needs Task 1 or 2, wastes Task 0 and the other
2. **Task Coupling**: Success/failure tasks have identical roles but both always execute
3. **No Feasibility Gate**: Infeasible actions aren't rejected until consequence evaluation
4. **Unclear Boundaries**: Judge generates narrative consequences (overlaps with Narrator)
5. **Single Agent Bottleneck**: All rule interpretation, validation, and consequence logic on one agent

---

## Proposed Hierarchical Architecture

### Option A: 3-Tier Hierarchy (Recommended)

**Structure**:
```
Manager Agent (Router/Orchestrator)
├─→ Feasibility Agent (Validates action against D&D rules)
├─→ Difficulty Agent (Assigns DC based on rules + context)
└─→ Consequence Agent (Evaluates mechanical effects of success/failure)
```

**Process Flow**:
1. Manager receives action from Flow
2. Manager → Feasibility Agent (checks if action is valid)
   - If invalid: Return rejection to Narrator (skip difficulty check)
3. Manager → Difficulty Agent (assigns DC)
4. Flow performs d20 roll (Interface/GUI)
5. Manager → Consequence Agent (evaluates effect based on roll vs DC)
6. Return effect to Flow

**Key Change**: Conditional execution + role-based specialization

---

### Option B: 2-Tier Hierarchy (Simpler)

**Structure**:
```
Judge Manager Agent
├─→ Rule Evaluator Agent (Difficulty + Feasibility)
└─→ Effect Evaluator Agent (Consequences)
```

Simpler but less granular specialization.

---

### Option C: Flat Multi-Agent (Parallel)

**Structure**:
```
Three independent agents (no manager):
- Feasibility Agent
- Difficulty Agent
- Consequence Agent
```

**Process**: CrewAI hierarchical process with manager LLM auto-routing tasks.

---

## Advantages of Hierarchical Approach

### 1. **Token Efficiency** ⭐⭐⭐⭐⭐
**Problem Solved**: Eliminates redundant task execution.

**Current**: All 3 tasks execute every time = ~3x token cost
**Hierarchical**: Only execute needed tasks = ~40-60% token reduction

**Example**:
- Current: First call executes check_difficulty + good_action_result + bad_action_result (3 tasks)
- Hierarchical: First call executes check_difficulty only (1 task)

**Impact**:
- Reduces LLM API costs significantly (Gemini charges per token)
- Faster response times (fewer tasks = less latency)

---

### 2. **Clear Separation of Concerns** ⭐⭐⭐⭐
**Problem Solved**: Removes task overlap and unclear boundaries.

**Benefits**:
- **Feasibility Agent**: Pure rule validation (D&D 5E legal action?)
- **Difficulty Agent**: Pure DC assignment (how hard is this?)
- **Consequence Agent**: Pure effect evaluation (what happens?)
- **Manager Agent**: Orchestrates flow, doesn't do domain work

**Contrast with Current**:
- Current: Single agent must mentally context-switch between 3 cognitive tasks
- Hierarchical: Each agent has one focused responsibility

**Example**:
```
Current: Judge agent thinks about difficulty, then success effects, then failure effects (serial multitasking)
Hierarchical: Difficulty agent only thinks about DC assignment (focused expertise)
```

---

### 3. **Early Action Rejection** ⭐⭐⭐⭐
**Problem Solved**: Catches invalid actions before difficulty check.

**Benefits**:
- **Faster Feedback**: User gets immediate clarification for impossible actions
- **Reduced Computational Waste**: No need to evaluate difficulty/consequences for invalid actions
- **Better UX**: Clear error messages ("You cannot cast spells in melee range without War Caster feat")

**Current Behavior**:
```
User: "I cast Fireball while grappled"
→ Evaluate difficulty (waste tokens)
→ Perform roll (waste time)
→ Evaluate consequences (finally reject as infeasible)
```

**Hierarchical Behavior**:
```
User: "I cast Fireball while grappled"
→ Feasibility check: "Invalid - you cannot cast verbal spells while silenced"
→ Skip difficulty + roll (save tokens + time)
```

---

### 4. **Conditional Task Execution** ⭐⭐⭐⭐
**Problem Solved**: Execute only necessary tasks based on context.

**Routing Logic**:
```python
if not feasible:
    return rejection_message
elif skip_difficulty_check:  # DC -1 or 21
    skip_roll()
    return auto_consequence
elif roll > dc:
    return success_consequence_only  # Don't execute failure task
else:
    return failure_consequence_only  # Don't execute success task
```

**Current**: Always executes both success and failure consequence tasks.

**Impact**:
- **50% reduction** in consequence evaluation tokens (only execute one branch)
- **Cleaner logic**: Manager routes to correct agent, not "execute both and choose later"

---

### 5. **Agent Specialization & Expertise** ⭐⭐⭐⭐
**Problem Solved**: Agents become domain experts.

**Specialization Benefits**:
- **Feasibility Agent**: Focuses on D&D 5E rule validation (action economy, spell components, feats)
- **Difficulty Agent**: Focuses on situational modifiers (terrain, visibility, enemy stats)
- **Consequence Agent**: Focuses on mechanical effects (HP changes, status conditions, position)

**LLM Context Management**:
- Smaller, more focused prompts per agent
- Each agent retrieves only relevant rules from vector DB
- Reduces "context pollution" (agent doesn't need to know about consequences when assigning difficulty)

**Example**:
- **Current**: Judge prompt includes rules for difficulty + consequences + feasibility (massive context)
- **Hierarchical**: Difficulty agent prompt only includes DC assignment rules (focused context)

---

### 6. **Parallel Processing Potential** ⭐⭐⭐
**Problem Solved**: Some tasks can execute concurrently.

**Parallelizable Operations**:
- **Feasibility + Difficulty** could execute in parallel if action is known to be valid
- **Multiple NPC consequence evaluations** could execute concurrently (future enhancement)

**Current**: All tasks execute sequentially on same agent.

**Note**: CrewAI Flows are synchronous, so true parallelism requires threading (like GUI implementation).

---

### 7. **Easier Testing & Debugging** ⭐⭐⭐
**Problem Solved**: Isolated agent testing.

**Benefits**:
- Test Feasibility Agent independently (validate rule coverage)
- Test Difficulty Agent with known scenarios (verify DC assignment)
- Test Consequence Agent with mock roll results (verify effect logic)
- Debug issues by agent role (easier to trace "Why was this action rejected?")

**Current**: All logic intertwined in single agent, harder to isolate failures.

---

### 8. **Scalability for Future Features** ⭐⭐⭐⭐
**Problem Solved**: Easier to add new decision types.

**Future Enhancements**:
- **Combat Manager Agent**: Handles initiative, turns, reactions
- **Economy Agent**: Validates resource spending (spell slots, gold, inventory)
- **Social Interaction Agent**: Evaluates persuasion/deception checks
- **Environmental Hazard Agent**: Evaluates trap triggers, falling damage

**Current**: Adding new logic requires modifying monolithic Judge agent.

**Hierarchical**: Add new specialized agent, register with Manager.

---

### 9. **Aligns with D&D Game Master Mental Model** ⭐⭐⭐⭐⭐
**Problem Solved**: Reflects how real DMs process actions.

**Real DM Thought Process**:
1. **Validate**: "Can the player do this?" (rule check)
2. **Difficulty**: "How hard is this?" (DC assignment)
3. **Resolution**: "What happens?" (roll + consequence)

**Current**: Single agent must simulate all 3 phases internally.

**Hierarchical**: Three agents mirror the 3 cognitive phases naturally.

**Benefit**: Easier to reason about system behavior, aligns with domain knowledge.

---

## Disadvantages of Hierarchical Approach

### 1. **Increased Complexity** ⭐⭐⭐⭐
**Trade-off**: More agents = more code to maintain.

**Complexity Factors**:
- **More Agent Definitions**: 3-4 agents vs. 1 agent (4x agent YAML config)
- **Manager Logic**: Routing logic must be implemented (conditional task execution)
- **Inter-Agent Communication**: More queues/state passing between agents
- **Debugging Overhead**: Harder to trace execution flow across multiple agents

**Mitigation**:
- Use clear naming conventions (`feasibility_agent`, `difficulty_agent`)
- Implement comprehensive logging (`[FeasibilityAgent] Checking action...`)
- CrewAI's hierarchical process helps (manager LLM auto-routes)

**Risk**: Junior developers may struggle to understand multi-agent flow.

---

### 2. **Manager Agent Overhead** ⭐⭐⭐
**Trade-off**: Manager adds extra LLM call for routing.

**Overhead**:
- **Token Cost**: Manager must analyze context to decide which agent to invoke
- **Latency**: Additional LLM inference for routing decisions
- **Potential Routing Errors**: Manager might route to wrong agent

**Example**:
```
Current: 1 LLM call (Judge directly processes action)
Hierarchical: 2 LLM calls (Manager routes → Specialized agent processes)
```

**Net Impact**:
- Token savings from conditional execution (60% reduction) > Manager overhead (10-20% increase)
- **Net savings: ~40-50%** (assuming half of tasks are skipped)

**Mitigation**:
- Use lightweight manager prompts ("Route this action to feasibility/difficulty/consequence agent")
- Consider rule-based routing for obvious cases (skip Manager LLM call)

---

### 3. **Context Fragmentation** ⭐⭐⭐
**Trade-off**: Each agent has limited context about full game state.

**Problem**:
- **Feasibility Agent** doesn't know about player HP (might allow risky action)
- **Difficulty Agent** doesn't know about previous failed attempts (can't adjust DC)
- **Consequence Agent** doesn't know about overarching story (might generate conflicting effects)

**Current**: Single agent has full context in one prompt.

**Hierarchical**: Context must be explicitly passed to each agent.

**Mitigation**:
- **Manager provides context**: Includes relevant game state in agent inputs
- **Shared State Object**: All agents access `HostState` for campaign/player info
- **Explicit Context Passing**: Manager extracts and injects needed context per agent

**Example**:
```python
# Manager prepares context for Difficulty Agent
difficulty_agent_input = {
    "action": action_extracted,
    "player_level": state.player_level,
    "relevant_rules": vector_search_results,
    "environmental_factors": state.current_venue_hazards
}
```

---

### 4. **Potential for Inconsistent Decisions** ⭐⭐
**Trade-off**: Different agents might interpret rules differently.

**Problem**:
- **Feasibility Agent** might validate an action as legal
- **Difficulty Agent** might later assign DC 21 (impossible) → Contradiction!

**Current**: Single agent ensures consistency (same LLM reasoning throughout).

**Hierarchical**: Different agent prompts → different interpretations.

**Mitigation**:
- **Shared Rule Base**: All agents query same MongoDB vector database
- **Agent Coordination**: Manager validates no contradictions (feasibility pass + DC 21 = error)
- **Standardized Prompts**: Use consistent terminology and rule references across agents

**Risk**: Low (CrewAI agents use same LLM backend, vector DB ensures consistent rule retrieval)

---

### 5. **Harder to Implement Cancel Action** ⭐⭐
**Trade-off**: User cancels during difficulty check → must clean up multiple agents.

**Problem** (in GUI context):
- Current: Cancel during difficulty check → single Judge agent stops
- Hierarchical: Cancel during difficulty check → Manager + Difficulty agent must both stop

**Mitigation**:
- Use same exception-based cancellation (`UserCancelledActionException`)
- Manager catches exception and cleans up all sub-agents
- Sub-agents are stateless (no cleanup needed)

**Impact**: Minimal (exception propagation works naturally in Python)

---

### 6. **Migration Complexity** ⭐⭐⭐⭐
**Trade-off**: Refactoring existing Judge requires significant code changes.

**Files to Modify**:
- `judge_crew.py`: Restructure from 1 agent to 3-4 agents
- `agents.yaml`: Define new agent roles/goals/backstories
- `tasks.yaml`: Redefine tasks for each agent
- `main.py`: Update Judge invocations (2 places in Flow)
- `tools/`: Potentially add new MongoDB vector search tools per agent

**Backward Compatibility**:
- Current code assumes `JudgeCrew().crew().kickoff()` returns specific structure
- Hierarchical structure might return different `tasks_output` format
- Must update Flow extraction logic (`result.tasks_output[0].to_dict()`)

**Testing Burden**:
- Existing tests break (agent structure changed)
- Need new integration tests for manager routing
- Need unit tests for each specialized agent

**Mitigation**:
- **Phased Rollout**: Implement hierarchical Judge alongside current Judge, switch via config flag
- **Adapter Pattern**: Wrap hierarchical Judge to return same output format as current Judge
- **Comprehensive Testing**: Write tests before refactoring

---

### 7. **Limited CrewAI Hierarchical Process Support** ⭐⭐⭐
**Trade-off**: CrewAI's hierarchical process has limitations.

**CrewAI Hierarchical Process Constraints** (v1.5.0):
- **Manager LLM Required**: Must use LLM for task delegation (not rule-based)
- **Sequential Execution**: Tasks assigned to sub-agents still execute sequentially
- **Limited Routing Control**: Can't easily implement "skip Task X if condition Y"

**Example Limitation**:
```python
# Can't do this easily in CrewAI hierarchical process:
if feasibility == False:
    return early  # Skip difficulty and consequence agents
```

**Workaround**:
- **Use Flow-Level Orchestration**: Manager is a Python class, not CrewAI agent
- **Conditional Crew Instantiation**: Only create/kickoff agents when needed

**Example**:
```python
# Manager as Python class (not CrewAI agent)
class JudgeManager:
    def evaluate_action(self, action):
        # Check feasibility
        if not FeasibilityCrew().kickoff(action).is_valid:
            return rejection

        # Check difficulty
        dc = DifficultyCrew().kickoff(action).difficulty

        # Return (don't execute consequence until roll is known)
        return dc
```

**Mitigation**: Use manual orchestration instead of CrewAI hierarchical process.

---

### 8. **Potential Token Cost Increase (If Poorly Implemented)** ⭐⭐
**Trade-off**: Bad routing logic could waste more tokens than current.

**Anti-Pattern**:
```python
# BAD: Execute all agents regardless of need
feasibility_result = FeasibilityCrew().kickoff()
difficulty_result = DifficultyCrew().kickoff()  # Waste if infeasible
consequence_result = ConsequenceCrew().kickoff()  # Waste if not rolled yet
```

**Result**: 3 separate crew kickoffs with manager overhead = **worse than current!**

**Mitigation**:
- **Conditional Execution**: Only kickoff agents when needed
- **Early Returns**: Exit as soon as rejection/impossibility detected
- **Profile Token Usage**: Monitor token consumption before/after migration

---

### 9. **Loss of Agent State (If Needed in Future)** ⭐⭐
**Trade-off**: Current single agent could maintain internal memory (like Narrator).

**Current**: Judge is stateless (doesn't maintain memory between kickoffs).

**Hypothetical Future Need**:
- "Remember player's previous failed attempts at this action" (adjust DC)
- "Track cumulative stress level" (increase DC over time)

**Problem**:
- Hierarchical structure with multiple agents → harder to maintain shared memory
- Each sub-agent would need independent memory (Feasibility memory, Difficulty memory)

**Current Single Agent**: Could maintain unified memory in one place.

**Mitigation**:
- Judge doesn't need memory for MVP (stateless rule application)
- If needed in future: Store memory in MongoDB or HostState, pass to all agents

**Risk**: Low (Judge is inherently stateless by design)

---

## Comparison Matrix

| Criterion | Current (Monolithic) | Hierarchical | Winner |
|-----------|---------------------|--------------|--------|
| **Token Efficiency** | ⭐⭐ (3 tasks always execute) | ⭐⭐⭐⭐⭐ (conditional execution) | Hierarchical |
| **Code Complexity** | ⭐⭐⭐⭐⭐ (simple) | ⭐⭐ (more components) | Monolithic |
| **Response Time** | ⭐⭐ (redundant tasks) | ⭐⭐⭐⭐ (faster with fewer tasks) | Hierarchical |
| **Separation of Concerns** | ⭐⭐ (overlapping responsibilities) | ⭐⭐⭐⭐⭐ (clear agent roles) | Hierarchical |
| **Early Rejection** | ⭐ (no feasibility gate) | ⭐⭐⭐⭐⭐ (immediate feedback) | Hierarchical |
| **Testing/Debugging** | ⭐⭐⭐ (monolithic testing) | ⭐⭐⭐⭐ (isolated agent tests) | Hierarchical |
| **Maintenance Burden** | ⭐⭐⭐⭐ (fewer files) | ⭐⭐ (more agents to maintain) | Monolithic |
| **Migration Effort** | N/A (current state) | ⭐ (significant refactor) | Monolithic |
| **Scalability** | ⭐⭐ (hard to extend) | ⭐⭐⭐⭐⭐ (easy to add agents) | Hierarchical |
| **Context Management** | ⭐⭐⭐⭐ (single context) | ⭐⭐⭐ (fragmented context) | Monolithic |
| **Domain Alignment** | ⭐⭐⭐ (1 agent = 1 DM) | ⭐⭐⭐⭐⭐ (mirrors DM thought process) | Hierarchical |

**Overall**: Hierarchical wins 7/10 criteria (excluding migration and N/A).

---

## Cost-Benefit Analysis

### Token Cost Projection

**Assumptions**:
- Average action requires: Feasibility (200 tokens) + Difficulty (300 tokens) + Consequence (400 tokens)
- Manager routing: 100 tokens
- Current approach: All 3 tasks execute twice (first call + second call)

**Current Token Usage per Action**:
```
First call: 200 + 300 + 400 = 900 tokens (only need difficulty = 300)
Second call: 200 + 300 + 400 = 900 tokens (only need consequence = 400)
Total: 1800 tokens per action
Wasted: 1800 - 700 = 1100 tokens (61% waste)
```

**Hierarchical Token Usage per Action**:
```
Manager (first): 100 tokens
Feasibility: 200 tokens
Difficulty: 300 tokens
Manager (second): 100 tokens
Consequence: 400 tokens
Total: 1100 tokens per action
Wasted: 0 tokens (0% waste)
Savings: 700 tokens per action (39% reduction)
```

**Scaled Impact** (100 actions per playthrough):
- Current: 180,000 tokens
- Hierarchical: 110,000 tokens
- **Savings: 70,000 tokens (~$0.05-$0.10 at Gemini pricing)**

**Conclusion**: Hierarchical approach pays for itself in token savings after ~20-30 actions.

---

### Development Time Estimate

**Implementation Phases**:
1. **Design** (4-6 hours): Define agent roles, task boundaries, routing logic
2. **Code Refactor** (8-12 hours): Split Judge into 3 agents + Manager
3. **Testing** (6-8 hours): Unit tests + integration tests
4. **Flow Integration** (4-6 hours): Update main.py invocations
5. **Documentation** (2-3 hours): Update CLAUDE.md, agent configs

**Total Estimate**: 24-35 hours

**Complexity**: Medium-High (requires deep understanding of CrewAI + Flow patterns)

---

## Recommendations

### When to Use Hierarchical Approach ✅

**Recommended If**:
1. **High usage expected**: Many actions per playthrough (token savings compound)
2. **Complex rule validation needed**: D&D 5E has intricate rules (feasibility gate valuable)
3. **Future feature expansion planned**: Want to add combat manager, economy agent, etc.
4. **Team has CrewAI expertise**: Developers comfortable with multi-agent patterns
5. **Performance matters**: Want faster response times (skip unnecessary tasks)

**Best For**:
- Production deployment with real users
- Long-form campaigns (many actions per session)
- Feature-rich game systems (combat, magic, social interactions)

---

### When to Keep Monolithic Approach ⛔

**Keep Current If**:
1. **Prototype/MVP stage**: Focus on proving core concept, not optimization
2. **Low usage expected**: Few actions per playthrough (token savings minimal)
3. **Limited development time**: 24-35 hours is too costly
4. **Team unfamiliar with multi-agent**: Risk of implementation errors
5. **Simple rule system**: Not using complex D&D 5E validation

**Best For**:
- Initial prototype/demo
- Short test scenarios
- Proof-of-concept for stakeholders

---

### Hybrid Approach (Recommended for Your Case) 🎯

**Phased Implementation**:

**Phase 1 (Now)**: Keep monolithic Judge, focus on GUI integration
- Reason: GUI is higher priority (user-facing feature)
- Judge works adequately for MVP (despite token waste)

**Phase 2 (After GUI Stable)**: Implement hierarchical Judge
- Reason: GUI provides user value; hierarchical Judge provides cost optimization
- Migrate when you have time for 24-35 hour refactor

**Phase 3 (Future)**: Add specialized agents
- Combat Manager Agent
- Economy Agent
- Social Interaction Agent

**Rationale**:
- GUI unlocks user testing → Validate game mechanics work
- Hierarchical Judge optimizes costs → Better for production scaling
- Specialized agents add richness → Enhanced gameplay experience

---

## Implementation Sketch (If You Proceed)

### Proposed File Structure
```
src/dnd_mas_host/crews/judge_crew/
├── judge_crew.py              # Manager crew (orchestrator)
├── feasibility_crew.py        # Feasibility check crew
├── difficulty_crew.py         # DC assignment crew
├── consequence_crew.py        # Effect evaluation crew
├── config/
│   ├── agents.yaml            # 4 agent definitions
│   ├── tasks.yaml             # 4 task definitions (one per agent)
│   └── manager_config.yaml    # Manager routing rules
└── __init__.py
```

### Manager Orchestration Logic
```python
class JudgeManager:
    def evaluate_action(self, action_data):
        # Phase 1: Feasibility
        feasibility_result = FeasibilityCrew().crew().kickoff(
            inputs={"action": action_data}
        )
        if not feasibility_result.is_valid:
            return {"valid": False, "message": feasibility_result.reason}

        # Phase 2: Difficulty
        difficulty_result = DifficultyCrew().crew().kickoff(
            inputs={"action": action_data}
        )
        return {
            "valid": True,
            "difficulty": difficulty_result.dc,
            "skip_check": difficulty_result.skip_check
        }

    def evaluate_consequence(self, action_data, roll, dc):
        # Phase 3: Consequence (success or failure)
        success = roll > dc
        consequence_result = ConsequenceCrew().crew().kickoff(
            inputs={
                "action": action_data,
                "success": success,
                "roll": roll,
                "dc": dc
            }
        )
        return {"effect": consequence_result.effect}
```

### Integration with Flow
```python
# main.py - Step 4: evaluate_difficulty
result = JudgeManager().evaluate_action(
    action_data=self.state.action_extracted
)
if not result["valid"]:
    # Send validation error to GUI
    self.gui_queues["from_flow"].put(create_message(
        MessageType.VALIDATION_ERROR,
        {"message": result["message"]}
    ))
    raise UserCancelledActionException("Invalid action")

self.state.Action_difficulty = result["difficulty"]
self.state.skip_difficulty_check = result["skip_check"]

# main.py - Step 6: evaluate_consequences
result = JudgeManager().evaluate_consequence(
    action_data=self.state.action_extracted,
    roll=self.state.difficulty_check,
    dc=self.state.Action_difficulty
)
self.state.effect = result["effect"]
```

---

## Conclusion

**TL;DR**:
- **Advantages**: Token efficiency (39% savings), clear separation of concerns, early rejection, scalability, aligns with D&D mental model
- **Disadvantages**: Increased complexity, manager overhead, migration effort, context fragmentation
- **Verdict**: **Hierarchical approach is beneficial** for production deployment, but **not critical for MVP**

**Recommendation**:
1. **Short-term**: Keep monolithic Judge, focus on GUI (high user value)
2. **Mid-term**: Refactor to hierarchical Judge (cost optimization)
3. **Long-term**: Add specialized agents (feature richness)

The hierarchical approach represents a **worthwhile optimization** but is **not blocking** for initial launch. Prioritize user-facing features (GUI) over internal optimizations (hierarchical Judge) until you have validated the core gameplay loop with real users.

---

## Next Steps (If You Decide to Proceed)

1. **Review this analysis** with your team/stakeholders
2. **Decide on timing**: Now vs. after GUI vs. after MVP validation?
3. **Choose architecture**: 3-tier (recommended) vs. 2-tier vs. flat?
4. **Plan migration**: Phased rollout vs. big-bang refactor?
5. **Design agent roles**: What rules does each agent specialize in?
6. **Implement & test**: Start with feasibility agent (lowest risk)
7. **Monitor metrics**: Compare token usage before/after migration

Would you like me to proceed with implementation planning, or would you prefer to focus on completing the GUI first?
