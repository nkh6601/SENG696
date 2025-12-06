"""
BlackboardManager for D&D MAS Host system.

This module provides centralized read/write access to HostState (Blackboard pattern)
with configurable logging for debugging state changes.
"""

from typing import List, Dict, Any, Optional, TYPE_CHECKING
from datetime import datetime

from dnd_mas_host.interface import character
from dnd_mas_host.state.host_state import (
    HostState,
    GameContext,
    TurnState,
    WorkflowState,
)

# Import config - will add ENABLE_BLACKBOARD_LOGGING
try:
    from dnd_mas_host.config import ENABLE_BLACKBOARD_LOGGING
except ImportError:
    ENABLE_BLACKBOARD_LOGGING = True  # Default to enabled if not configured

if TYPE_CHECKING:
    from dnd_mas_host.crews.npc_crew.npc_crew import NpcCrew


class BlackboardManager:
    """
    Centralized manager for HostState (Blackboard pattern).

    Responsibilities:
    - Provide read/write access to HostState
    - Log all state changes for debugging (configurable via config.py)
    - Validate writes for type safety
    - Provide atomic operations

    All agents (Interface, Narrator, Judge) access this directly.
    """

    def __init__(self, game_context: GameContext):
        """
        Initialize with immutable game context.

        Args:
            game_context: GameContext containing campaign, characters, venues data
        """
        self._blackboard = HostState(game_context=game_context)
        self._access_log: List[Dict[str, Any]] = []
        self._enable_logging = ENABLE_BLACKBOARD_LOGGING

    # ========================================================================
    # Core Access Methods
    # ========================================================================

    def read(self, keys: List[str]) -> Dict[str, Any]:
        """
        Read values from blackboard.

        Args:
            keys: List of dotted paths (e.g., ["workflow.current_step", "current_turn.prompt_text"])

        Returns:
            Dict mapping keys to values
        """
        result = {}
        for key in keys:
            value = self._get_nested_value(key)
            result[key] = value

        if self._enable_logging:
            self._log_access("READ", keys, result)

        return result

    def read_single(self, key: str) -> Any:
        """
        Read a single value from blackboard.

        Args:
            key: Dotted path (e.g., "workflow.current_step")

        Returns:
            The value at the specified path, or None if not found
        """
        result = self.read([key])
        return result.get(key)

    def write(self, updates: Dict[str, Any]) -> None:
        """
        Write values to blackboard.

        Args:
            updates: Dict mapping dotted paths to new values
                    (e.g., {"current_turn.prompt_text": "I attack", "workflow.current_step": "2_validate"})
        """
        if self._enable_logging:
            print("\n" + "=" * 80)
            print(f"[BLACKBOARD WRITE] {datetime.now().isoformat()}")
            print("=" * 80)

        for key, value in updates.items():
            old_value = self._get_nested_value(key)
            self._set_nested_value(key, value)

            if self._enable_logging:
                print(f"  {key}:")
                print(f"    OLD: {self._format_value(old_value)}")
                print(f"    NEW: {self._format_value(value)}")

        if self._enable_logging:
            print("=" * 80 + "\n")
            self._log_access("WRITE", list(updates.keys()), updates)

    def write_single(self, key: str, value: Any) -> None:
        """
        Write a single value to blackboard.

        Args:
            key: Dotted path (e.g., "current_turn.prompt_text")
            value: Value to set
        """
        self.write({key: value})

    def reset_turn(self) -> None:
        """
        Reset current_turn and workflow for new prompt.

        Preserves game_context and output.previous_* fields.
        """
        # Save previous turn context before reset
        previous_prompt = self._blackboard.current_turn.prompt_text
        previous_narrative = ""
        if self._blackboard.output.final_output:
            # Get the main character's narrative as previous
            mc_name = self._blackboard.game_context.main_character_name
            previous_narrative = self._blackboard.output.final_output.get(mc_name, "")

        # Reset turn state
        self._blackboard.current_turn = TurnState()
        self._blackboard.workflow = WorkflowState()

        # Store previous context in output
        self._blackboard.output.previous_prompt = previous_prompt
        self._blackboard.output.previous_narrative = previous_narrative

        if self._enable_logging:
            print("\n" + "=" * 80)
            print("[BLACKBOARD RESET] Turn state reset")
            print(f"  Previous prompt saved: {self._format_value(previous_prompt)}")
            print(f"  Previous narrative saved: {self._format_value(previous_narrative)}")
            print("=" * 80 + "\n")

    def get_snapshot(self) -> HostState:
        """
        Get full blackboard snapshot (for debugging).

        Returns:
            Deep copy of current HostState
        """
        return self._blackboard.model_copy(deep=True)

    def get_state(self) -> HostState:
        """
        Get direct reference to blackboard state.

        Warning: This returns the actual state object, not a copy.
        Use get_snapshot() if you need an immutable copy.

        Returns:
            Reference to current HostState
        """
        return self._blackboard

    # ========================================================================
    # Convenience Methods
    # ========================================================================

    def update_active_npcs(self, npc_crews: Dict[str, "NpcCrew"]) -> List[str]:
        """
        Update active_npc_names based on current_venue + companions.
        Manages NPC crew dict: REUSE existing, CREATE new, DELETE inactive.

        Called by HostManager when message.to == "NPC".

        Args:
            npc_crews: Reference to HostManager's npc_crews dict (mutable)

        Returns:
            List of active character names sorted by DEX (high to low)
        """
        current_venue_name = self._blackboard.game_context.current_venue_name
        all_venues = self._blackboard.game_context.all_venues
        all_npcs = self._blackboard.game_context.all_npcs
        all_characters = self._blackboard.game_context.all_characters
        companion_names = self._blackboard.game_context.companion_names

        # Get current venue data
        current_venue = all_venues.get(current_venue_name, {})
        npcs_in_venue = current_venue.get("npcs_present", [])

        # Collect all characters that should be active
        active_char_names = set()
        active_chars_with_dex = []

        # Add NPCs from current venue (filter dead ones)
        for npc_name in npcs_in_venue:
            if npc_name in all_npcs:
                npc_data = all_npcs[npc_name]
                # Check if NPC is alive (default to alive if no flag)
                is_alive = npc_data.get("is_alive", True)
                if npc_data.get("current_hit_points", 1) <= 0:
                    is_alive = False

                if is_alive:
                    dex = npc_data.get("dexterity", 10)
                    active_chars_with_dex.append((npc_name, dex))
                    active_char_names.add(npc_name)

        # Add companions (filter dead ones)
        for comp_name in companion_names:
            if comp_name in all_characters:
                companion_data = all_characters[comp_name]
                is_alive = companion_data.get("is_alive", True)
                if companion_data.get("current_hit_points", 1) <= 0:
                    is_alive = False

                if is_alive:
                    dex = companion_data.get("dexterity", 10)
                    active_chars_with_dex.append((comp_name, dex))
                    active_char_names.add(comp_name)

        # Sort by DEX (high to low)
        active_chars_with_dex.sort(key=lambda x: x[1], reverse=True)
        sorted_names = [name for name, _ in active_chars_with_dex]

        # Update blackboard
        self._blackboard.current_turn.active_npc_names = sorted_names

        # Manage NPC crews dict:
        # 1. DELETE crews for characters no longer active
        inactive_names = set(npc_crews.keys()) - active_char_names
        for name in inactive_names:
            del npc_crews[name]
            if self._enable_logging:
                print(f"[BLACKBOARD] Deleted NPC crew for: {name}")

        # 2. CREATE new crews only for new characters (done by HostManager)
        # Here we just return which crews need to be created
        new_char_names = active_char_names - set(npc_crews.keys())

        if self._enable_logging:
            print(f"[BLACKBOARD] Active NPCs (DEX order): {sorted_names}")
            if new_char_names:
                print(f"[BLACKBOARD] New crews needed for: {list(new_char_names)}")

        return sorted_names

    def get_npc_data(self, npc_name: str) -> Optional[Dict[str, Any]]:
        """
        Get NPC data by name from all_npcs.

        Args:
            npc_name: Name of the NPC

        Returns:
            NPC data dict or None if not found
        """
        return self._blackboard.game_context.all_npcs.get(npc_name)

    def get_character_data(self, char_name: str) -> Optional[Dict[str, Any]]:
        """
        Get character data by name from all_characters.

        Args:
            char_name: Name of the character

        Returns:
            Character data dict or None if not found
        """
        return self._blackboard.game_context.all_characters.get(char_name)

    def get_venue_data(self, venue_name: str) -> Optional[Dict[str, Any]]:
        """
        Get venue data by name from all_venues.

        Args:
            venue_name: Name of the venue

        Returns:
            Venue data dict or None if not found
        """
        return self._blackboard.game_context.all_venues.get(venue_name)

    def get_current_venue_data(self) -> Optional[Dict[str, Any]]:
        """
        Get current venue data.

        Returns:
            Current venue data dict or None if not found
        """
        return self.get_venue_data(self._blackboard.game_context.current_venue_name)

    # ========================================================================
    # Internal Helpers
    # ========================================================================

    def _get_nested_value(self, key: str) -> Any:
        """
        Get value from nested path (e.g., 'workflow.current_step').

        Args:
            key: Dotted path string

        Returns:
            Value at path or None if not found
        """
        parts = key.split('.')
        value = self._blackboard

        for part in parts:
            if hasattr(value, part):
                value = getattr(value, part)
            elif isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return None
        return value

    def _set_nested_value(self, key: str, value: Any) -> None:
        """
        Set value at nested path (e.g., 'workflow.current_step').

        Args:
            key: Dotted path string
            value: Value to set
        """
        parts = key.split('.')
        obj = self._blackboard

        # Navigate to parent
        for part in parts[:-1]:
            if hasattr(obj, part):
                obj = getattr(obj, part)
            elif isinstance(obj, dict):
                if part not in obj:
                    obj[part] = {}
                obj = obj[part]

        # Set final value
        final_key = parts[-1]
        if hasattr(obj, final_key):
            setattr(obj, final_key, value)
        elif isinstance(obj, dict):
            obj[final_key] = value

    def _format_value(self, value: Any) -> str:
        """
        Format value for readable logging.

        Args:
            value: Any value to format

        Returns:
            Human-readable string representation
        """
        if value is None:
            return "None"
        elif isinstance(value, (str, int, float, bool)):
            if isinstance(value, str) and len(value) > 100:
                return f'"{value[:100]}..."'
            return repr(value)
        elif isinstance(value, list):
            return f"List[{len(value)} items]"
        elif isinstance(value, dict):
            return f"Dict[{len(value)} keys]"
        else:
            return f"{type(value).__name__} object"

    def _log_access(self, operation: str, keys: List[str], data: Dict[str, Any]) -> None:
        """
        Log access for debugging and audit trail.

        Args:
            operation: "READ" or "WRITE"
            keys: Keys accessed
            data: Data read or written
        """
        self._access_log.append({
            "timestamp": datetime.now().isoformat(),
            "operation": operation,
            "keys": keys,
            "data_summary": {k: self._format_value(v) for k, v in data.items()}
        })

    def get_access_log(self) -> List[Dict[str, Any]]:
        """
        Get the access log for debugging.

        Returns:
            List of access log entries
        """
        return self._access_log.copy()

    def clear_access_log(self) -> None:
        """Clear the access log."""
        self._access_log.clear()
        
    def praseState(self) -> None:
        prompt_text = self.read_single("current_turn.prompt_text")
        mc_name = self.read_single("game_context.main_character_name")

        stage_name = self.read_single("game_context.current_stage_name")
        # Get venue and stage data
        venue_data = self.get_current_venue_data() or {}
        stage_data = self.read_single("game_context.all_stages").get(stage_name, {})
        mc_data  = self.get_character_data(mc_name) or {}

        
        # Get active NPCs in venue
        active_npcs = []
        npc_names = venue_data.get("NPCs", [])
        for npc_name in npc_names:
            npc_data = self.get_npc_data(npc_name)
            if npc_data:
                active_npcs.append(f"NPC name:{str(npc_data.get("name", []))}, desc{str(npc_data.get("desc", []))}, intention{str(npc_data.get("intention", []))}" )
                
                
        print(venue_data)
        
        result = f"Player prompt: {prompt_text} \
                    Main character: {mc_name}, HP: {mc_data["hp"]} , max HP: {mc_data["max_hp"]}, class: {str(mc_data["character_class"])}, level: {str(mc_data["level"])}\
                    stage: {str(stage_data["name"])}, description {str(stage_data.get("envDesc", []))}; {str(stage_data.get("storyDesc", []))}\
                    venue: {str(venue_data.get("name", []))}, description {str(venue_data.get("envDesc", []))}; {str(venue_data.get("storyDesc", []))}, potential valid action: {str(venue_data.get("actions", []))}, potential valid action: {",".join(venue_data.get("connectVenues", []))} \
                    NPCs nearby: {','.join(active_npcs)}"
                   
        print(result) 
        return result