"""
ConsequenceApplicator for D&D MAS Host system.

This module applies consequences to game state, updating character HP,
status effects, inventory, venue/stage state, and NPC states.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime

from dnd_mas_host.state.host_state import Consequence, ConsequenceType
from dnd_mas_host.state.blackboard_manager import BlackboardManager


class ConsequenceApplicator:
    """
    Applies consequences to game state.

    Responsibilities:
    - Update character HP, status effects, inventory
    - Update venue/stage state
    - Update NPC states (attitude, intentions)
    - Log all changes for narrative context

    The applicator reads from and writes to the BlackboardManager,
    updating the all_characters and all_npcs dictionaries as needed.
    """

    def __init__(self, blackboard: BlackboardManager):
        """
        Initialize with reference to BlackboardManager.

        Args:
            blackboard: BlackboardManager instance for state access
        """
        self.blackboard = blackboard
        self.change_log: List[str] = []

    def apply_consequences(self, consequences: List[Consequence]) -> List[str]:
        """
        Apply list of consequences to game state.

        Args:
            consequences: List of Consequence objects

        Returns:
            List of change log entries describing what was applied
        """
        self.change_log.clear()

        for consequence in consequences:
            self._apply_single_consequence(consequence)

        if self.change_log:
            print("[ConsequenceApplicator] Applied consequences:")
            for log in self.change_log:
                print(f"  - {log}")

        return self.change_log.copy()

    def apply_mc_consequences(self) -> List[str]:
        """
        Apply main character consequences from blackboard.

        Reads mc_consequence from current_turn and applies them.

        Returns:
            List of change log entries
        """
        consequences = self.blackboard.read_single("current_turn.mc_consequence") or []
        return self.apply_consequences(consequences)

    def apply_all_consequences(self) -> List[str]:
        """
        Apply all consequences (MC + NPC reactions) from blackboard.

        Returns:
            List of all change log entries
        """
        all_logs = []

        # Apply MC consequences
        mc_consequences = self.blackboard.read_single("current_turn.mc_consequence") or []
        all_logs.extend(self.apply_consequences(mc_consequences))

        # Apply NPC reaction consequences
        reactions_consequences = self.blackboard.read_single("current_turn.reactions_consequence_list") or {}
        for npc_name, npc_consequences in reactions_consequences.items():
            if npc_consequences:
                self.change_log.clear()
                for consequence in npc_consequences:
                    self._apply_single_consequence(consequence)
                all_logs.extend(self.change_log)

        return all_logs

    def _apply_single_consequence(self, consequence: Consequence) -> None:
        """
        Apply a single consequence based on its type.

        Args:
            consequence: Consequence object to apply
        """
        if consequence.consequence_type == ConsequenceType.DAMAGE:
            self._apply_damage(consequence)

        elif consequence.consequence_type == ConsequenceType.HEALING:
            self._apply_healing(consequence)

        elif consequence.consequence_type == ConsequenceType.MOVEMENT:
            self._apply_movement(consequence)

        elif consequence.consequence_type == ConsequenceType.STATUS_EFFECT:
            self._apply_status_effect(consequence)

        elif consequence.consequence_type == ConsequenceType.ITEM_CHANGE:
            self._apply_item_change(consequence)

        elif consequence.consequence_type == ConsequenceType.VENUE_CHANGE:
            self._apply_venue_change(consequence)

        elif consequence.consequence_type == ConsequenceType.STAGE_CHANGE:
            self._apply_stage_change(consequence)

        elif consequence.consequence_type == ConsequenceType.NPC_STATE_CHANGE:
            self._apply_npc_state_change(consequence)

        elif consequence.consequence_type == ConsequenceType.ENVIRONMENTAL:
            self._apply_environmental(consequence)

    def _get_character_data(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Get character data by name from all_characters or all_npcs.

        Args:
            name: Character name

        Returns:
            Character data dict or None
        """
        # Try all_characters first (PCs)
        char_data = self.blackboard.get_character_data(name)
        if char_data:
            return char_data

        # Try all_npcs
        return self.blackboard.get_npc_data(name)

    def _update_character_data(self, name: str, updates: Dict[str, Any]) -> None:
        """
        Update character data in blackboard.

        Args:
            name: Character name
            updates: Dict of field updates
        """
        # Check if PC or NPC
        all_characters = self.blackboard.read_single("game_context.all_characters") or {}
        all_npcs = self.blackboard.read_single("game_context.all_npcs") or {}

        if name in all_characters:
            char_data = all_characters[name]
            char_data.update(updates)
            self.blackboard.write({f"game_context.all_characters.{name}": char_data})
        elif name in all_npcs:
            npc_data = all_npcs[name]
            npc_data.update(updates)
            self.blackboard.write({f"game_context.all_npcs.{name}": npc_data})

    def _apply_damage(self, consequence: Consequence) -> None:
        """
        Apply damage to target.

        Args:
            consequence: Damage consequence
        """
        target_name = consequence.target_name
        damage = consequence.damage_amount or 0
        damage_type = consequence.damage_type or "untyped"

        char_data = self._get_character_data(target_name)
        if not char_data:
            self.change_log.append(f"Target '{target_name}' not found for damage")
            return

        old_hp = char_data.get("current_hit_points", char_data.get("hit_points", 0))
        new_hp = max(0, old_hp - damage)

        self._update_character_data(target_name, {"current_hit_points": new_hp})

        self.change_log.append(
            f"{target_name} takes {damage} {damage_type} damage ({old_hp} -> {new_hp} HP)"
        )

        if new_hp == 0:
            self.change_log.append(f"{target_name} is unconscious!")
            # Mark as not alive
            self._update_character_data(target_name, {"is_alive": False})

    def _apply_healing(self, consequence: Consequence) -> None:
        """
        Apply healing to target.

        Args:
            consequence: Healing consequence
        """
        target_name = consequence.target_name
        healing = consequence.healing_amount or 0

        char_data = self._get_character_data(target_name)
        if not char_data:
            self.change_log.append(f"Target '{target_name}' not found for healing")
            return

        old_hp = char_data.get("current_hit_points", char_data.get("hit_points", 0))
        max_hp = char_data.get("hit_points", old_hp)
        new_hp = min(max_hp, old_hp + healing)

        self._update_character_data(target_name, {"current_hit_points": new_hp})

        self.change_log.append(
            f"{target_name} heals {healing} HP ({old_hp} -> {new_hp} HP)"
        )

        # If was unconscious and now has HP, mark alive
        if old_hp == 0 and new_hp > 0:
            self._update_character_data(target_name, {"is_alive": True})
            self.change_log.append(f"{target_name} regains consciousness!")

    def _apply_movement(self, consequence: Consequence) -> None:
        """
        Apply movement to new location.

        Args:
            consequence: Movement consequence
        """
        new_venue = consequence.new_location
        if not new_venue:
            return

        # Update current venue in game context
        self.blackboard.write({"game_context.current_venue_name": new_venue})

        self.change_log.append(f"Moved to {new_venue}")

    def _apply_status_effect(self, consequence: Consequence) -> None:
        """
        Apply status effect to target.

        Args:
            consequence: Status effect consequence
        """
        target_name = consequence.target_name
        effect = consequence.status_effect
        duration = consequence.duration

        if not effect:
            return

        char_data = self._get_character_data(target_name)
        if not char_data:
            self.change_log.append(f"Target '{target_name}' not found for status effect")
            return

        # Get existing conditions or create new list
        conditions = char_data.get("conditions", [])
        if not isinstance(conditions, list):
            conditions = []

        # Add new condition
        condition_entry = {
            "effect": effect,
            "duration": duration,
            "applied_at": datetime.now().isoformat()
        }
        conditions.append(condition_entry)

        self._update_character_data(target_name, {"conditions": conditions})

        duration_str = f" (duration: {duration} turns)" if duration else ""
        self.change_log.append(f"{target_name} is now {effect}{duration_str}")

    def _apply_item_change(self, consequence: Consequence) -> None:
        """
        Apply item changes to target.

        Args:
            consequence: Item change consequence
        """
        target_name = consequence.target_name

        char_data = self._get_character_data(target_name)
        if not char_data:
            self.change_log.append(f"Target '{target_name}' not found for item change")
            return

        # Get existing inventory
        inventory = char_data.get("inventory", [])
        if not isinstance(inventory, list):
            inventory = []

        # Add gained item
        if consequence.item_gained:
            inventory.append(consequence.item_gained)
            self._update_character_data(target_name, {"inventory": inventory})
            self.change_log.append(f"{target_name} gained {consequence.item_gained}")

        # Remove lost item
        if consequence.item_lost:
            if consequence.item_lost in inventory:
                inventory.remove(consequence.item_lost)
                self._update_character_data(target_name, {"inventory": inventory})
                self.change_log.append(f"{target_name} lost {consequence.item_lost}")
            else:
                self.change_log.append(
                    f"{target_name} doesn't have {consequence.item_lost} to lose"
                )

    def _apply_venue_change(self, consequence: Consequence) -> None:
        """
        Apply changes to venue state (traps triggered, doors opened, etc.).

        Args:
            consequence: Venue change consequence
        """
        # For now, just log the venue change
        # In a full implementation, you'd update venue-specific state
        self.change_log.append(f"Venue changed: {consequence.description}")

    def _apply_stage_change(self, consequence: Consequence) -> None:
        """
        Apply changes to stage progression.

        Args:
            consequence: Stage change consequence
        """
        new_stage = consequence.new_location
        if not new_stage:
            return

        # Update current stage
        self.blackboard.write({"game_context.current_stage_name": new_stage})

        # If the new stage has a start venue, update venue too
        stages = self.blackboard.read_single("game_context.all_stages") or {}
        if new_stage in stages:
            stage_data = stages[new_stage]
            start_venue = stage_data.get("startVenue")
            if start_venue:
                self.blackboard.write({"game_context.current_venue_name": start_venue})
                self.change_log.append(f"Stage progressed to {new_stage}, entering {start_venue}")
            else:
                self.change_log.append(f"Stage progressed to {new_stage}")
        else:
            self.change_log.append(f"Stage progressed to {new_stage}")

    def _apply_npc_state_change(self, consequence: Consequence) -> None:
        """
        Apply changes to NPC internal state (attitude, intentions, etc.).

        Args:
            consequence: NPC state change consequence
        """
        target_name = consequence.target_name
        state_changes = consequence.npc_state_change

        if not state_changes:
            return

        npc_data = self.blackboard.get_npc_data(target_name)
        if not npc_data:
            self.change_log.append(f"NPC '{target_name}' not found for state change")
            return

        # Apply each state change
        for key, value in state_changes.items():
            npc_data[key] = value

        # Write back to blackboard
        all_npcs = self.blackboard.read_single("game_context.all_npcs") or {}
        all_npcs[target_name] = npc_data
        self.blackboard.write({"game_context.all_npcs": all_npcs})

        self.change_log.append(f"{target_name} state changed: {consequence.description}")

    def _apply_environmental(self, consequence: Consequence) -> None:
        """
        Apply environmental consequences.

        Args:
            consequence: Environmental consequence
        """
        # Environmental consequences are narrative/descriptive
        # They're logged but don't directly modify game state
        self.change_log.append(f"Environmental: {consequence.description}")

    # ========================================================================
    # Utility Methods
    # ========================================================================

    def decrement_status_durations(self) -> List[str]:
        """
        Decrement status effect durations at end of turn.

        Removes expired status effects.

        Returns:
            List of status changes
        """
        changes = []

        # Process all characters
        all_characters = self.blackboard.read_single("game_context.all_characters") or {}
        for char_name, char_data in all_characters.items():
            char_changes = self._process_character_conditions(char_name, char_data)
            changes.extend(char_changes)

        # Process all NPCs
        all_npcs = self.blackboard.read_single("game_context.all_npcs") or {}
        for npc_name, npc_data in all_npcs.items():
            npc_changes = self._process_character_conditions(npc_name, npc_data)
            changes.extend(npc_changes)

        return changes

    def _process_character_conditions(
        self, name: str, data: Dict[str, Any]
    ) -> List[str]:
        """
        Process conditions for a single character.

        Args:
            name: Character name
            data: Character data dict

        Returns:
            List of changes
        """
        changes = []
        conditions = data.get("conditions", [])

        if not conditions:
            return changes

        remaining_conditions = []
        for condition in conditions:
            duration = condition.get("duration")
            effect = condition.get("effect", "unknown")

            if duration is None:
                # Permanent condition
                remaining_conditions.append(condition)
            elif duration > 1:
                # Decrement duration
                condition["duration"] = duration - 1
                remaining_conditions.append(condition)
                changes.append(f"{name}'s {effect} has {duration - 1} turns remaining")
            else:
                # Duration expired
                changes.append(f"{name} is no longer {effect}")

        # Update character with remaining conditions
        self._update_character_data(name, {"conditions": remaining_conditions})

        return changes

    def check_death(self, character_name: str) -> bool:
        """
        Check if a character is dead (HP <= 0).

        Args:
            character_name: Name of character to check

        Returns:
            True if character is dead
        """
        char_data = self._get_character_data(character_name)
        if not char_data:
            return False

        current_hp = char_data.get("current_hit_points", char_data.get("hit_points", 1))
        return current_hp <= 0