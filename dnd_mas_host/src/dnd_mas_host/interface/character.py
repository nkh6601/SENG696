"""
Character model for D&D Multi-Agent System.

This module defines the Character model which represents both Player Characters (PCs)
and Non-Player Characters (NPCs) with their stats, equipment, and abilities.
"""

from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from enum import Enum


class CharacterType(str, Enum):
    """Character type enumeration"""
    MAIN_CHARACTER = "main_character"
    COMPANION = "companion"
    NPC = "npc"
    ENEMY = "enemy"


class Character(BaseModel):
    """
    Character model representing a PC or NPC.

    This model can be populated from MongoDB PCs or NPCs collections
    and provides a consistent interface for character data across the system.
    """
    # Identity
    name: str = Field(description="Character name")
    character_type: CharacterType = Field(description="Character type (main_character, companion, npc, enemy)")
    index: Optional[str] = Field(default=None, description="MongoDB index/ID (e.g., 'aldric-stormward')")

    # Class and level
    character_class: str = Field(default="", description="Character class (Fighter, Rogue, etc.)")
    level: int = Field(default=1, description="Character level")
    background: str = Field(default="", description="Character background")

    # Core stats
    hp: int = Field(description="Current hit points")
    max_hp: int = Field(description="Maximum hit points")
    ac: int = Field(default=10, description="Armor class")

    # Ability scores (optional, for more detailed stats)
    strength: Optional[int] = Field(default=None, description="Strength score")
    dexterity: Optional[int] = Field(default=None, description="Dexterity score")
    constitution: Optional[int] = Field(default=None, description="Constitution score")
    intelligence: Optional[int] = Field(default=None, description="Intelligence score")
    wisdom: Optional[int] = Field(default=None, description="Wisdom score")
    charisma: Optional[int] = Field(default=None, description="Charisma score")

    # Proficiencies and abilities
    skills: List[str] = Field(default_factory=list, description="Skill proficiencies")
    saving_throws: List[str] = Field(default_factory=list, description="Saving throw proficiencies")

    # Equipment and items
    equipment: List[Dict[str, Any]] = Field(default_factory=list, description="Equipment list with details")
    inventory: List[str] = Field(default_factory=list, description="Simple inventory item names")

    # Spells (for spellcasters)
    spells: List[Dict[str, Any]] = Field(default_factory=list, description="Known/prepared spells")
    spell_slots: Optional[Dict[str, int]] = Field(default=None, description="Available spell slots by level")

    # Status tracking
    conditions: List[str] = Field(default_factory=list, description="Active conditions (poisoned, prone, etc.)")
    temp_hp: int = Field(default=0, description="Temporary hit points")

    # Location and state
    location: Optional[str] = Field(default=None, description="Current location/venue")

    # NPC-specific fields
    personality: Optional[str] = Field(default=None, description="NPC personality traits")
    intentions: Optional[List[str]] = Field(default=None, description="NPC intentions/goals")
    description: Optional[str] = Field(default=None, description="Physical description")

    @classmethod
    def from_pc_document(cls, pc_doc: Dict[str, Any]) -> "Character":
        """
        Create Character from MongoDB PCs collection document.

        Args:
            pc_doc: MongoDB document from PCs collection

        Returns:
            Character instance populated with PC data
        """
        # Extract armor class (handle both dict and list formats)
        ac_data = pc_doc.get("armor_class", [])
        if isinstance(ac_data, list) and len(ac_data) > 0:
            ac = ac_data[0].get("value", 10)
        elif isinstance(ac_data, dict):
            ac = ac_data.get("value", 10)
        else:
            ac = 10

        # Extract skills from proficiencies
        skills = [
            prof["proficiency"]["name"]
            for prof in pc_doc.get("proficiencies", [])
            if prof.get("proficiency", {}).get("name")
        ]

        # Extract saving throws
        saving_throws = [
            st.get("name", "")
            for st in pc_doc.get("saving_throws", [])
        ]

        # Extract ability scores
        ability_scores = {}
        for ability in ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]:
            ability_scores[ability] = pc_doc.get(ability)

        # Extract spell slots (if any)
        spell_slots = None
        if "spell_slots" in pc_doc:
            spell_slots = pc_doc["spell_slots"]

        # Extract current location from status
        location = None
        if "current_status" in pc_doc:
            location = pc_doc["current_status"].get("location")

        # Determine character type
        char_type = CharacterType.MAIN_CHARACTER
        if pc_doc.get("character_type") == "companion":
            char_type = CharacterType.COMPANION

        return cls(
            name=pc_doc.get("name", "Unknown"),
            character_type=char_type,
            index=pc_doc.get("index"),
            character_class=pc_doc.get("class", ""),
            level=pc_doc.get("level", 1),
            background=pc_doc.get("background", ""),
            hp=pc_doc.get("current_hit_points", pc_doc.get("hit_points", 1)),
            max_hp=pc_doc.get("hit_points", 1),
            ac=ac,
            strength=ability_scores.get("strength"),
            dexterity=ability_scores.get("dexterity"),
            constitution=ability_scores.get("constitution"),
            intelligence=ability_scores.get("intelligence"),
            wisdom=ability_scores.get("wisdom"),
            charisma=ability_scores.get("charisma"),
            skills=skills,
            saving_throws=saving_throws,
            equipment=pc_doc.get("equipment", []),
            inventory=[],  # Could extract from equipment if needed
            spells=pc_doc.get("spells", []),
            spell_slots=spell_slots,
            conditions=pc_doc.get("current_status", {}).get("conditions", []),
            temp_hp=pc_doc.get("current_status", {}).get("temp_hp", 0),
            location=location
        )

    @classmethod
    def from_npc_document(cls, npc_doc: Dict[str, Any]) -> "Character":
        """
        Create Character from MongoDB NPCs collection document.

        Args:
            npc_doc: MongoDB document from NPCs collection

        Returns:
            Character instance populated with NPC data
        """
        # NPCs typically reference monster stats from 5e-database
        # Extract available information

        # Get stats from monster reference or NPC-specific stats
        stats = npc_doc.get("stats", {})
        monster_ref = npc_doc.get("monster_reference", {})

        hp = stats.get("hit_points", monster_ref.get("hit_points", 10))
        ac_data = stats.get("armor_class", monster_ref.get("armor_class", []))

        # Handle AC format
        if isinstance(ac_data, list) and len(ac_data) > 0:
            ac = ac_data[0].get("value", 10)
        elif isinstance(ac_data, dict):
            ac = ac_data.get("value", 10)
        elif isinstance(ac_data, int):
            ac = ac_data
        else:
            ac = 10

        # Get ability scores if available
        ability_scores = {}
        for ability in ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]:
            ability_scores[ability] = stats.get(ability) or monster_ref.get(ability)

        return cls(
            name=npc_doc.get("name", "Unknown NPC"),
            character_type=CharacterType.NPC,
            index=npc_doc.get("_id"),
            character_class=npc_doc.get("type", "NPC"),
            level=npc_doc.get("challenge_rating", 1),
            background="",
            hp=npc_doc.get("current_hit_points", hp),
            max_hp=hp,
            ac=ac,
            strength=ability_scores.get("strength"),
            dexterity=ability_scores.get("dexterity"),
            constitution=ability_scores.get("constitution"),
            intelligence=ability_scores.get("intelligence"),
            wisdom=ability_scores.get("wisdom"),
            charisma=ability_scores.get("charisma"),
            skills=[],  # Could extract from NPC doc
            saving_throws=[],
            equipment=[],
            inventory=[],
            spells=npc_doc.get("spells", []),
            spell_slots=None,
            conditions=npc_doc.get("current_status", {}).get("conditions", []),
            temp_hp=0,
            location=npc_doc.get("current_status", {}).get("location"),
            personality=npc_doc.get("personality"),
            intentions=npc_doc.get("intention", []),
            description=npc_doc.get("description")
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert Character to dictionary for serialization.

        Returns:
            Dictionary representation of character
        """
        return self.model_dump()

    def update_hp(self, new_hp: int):
        """
        Update character HP, clamping to valid range [0, max_hp].

        Args:
            new_hp: New HP value
        """
        self.hp = max(0, min(new_hp, self.max_hp))

    def take_damage(self, damage: int):
        """
        Apply damage to character (reduces HP).

        Args:
            damage: Amount of damage to take
        """
        # First reduce temp HP
        if self.temp_hp > 0:
            if damage <= self.temp_hp:
                self.temp_hp -= damage
                return
            else:
                damage -= self.temp_hp
                self.temp_hp = 0

        # Then reduce regular HP
        self.hp = max(0, self.hp - damage)

    def heal(self, healing: int):
        """
        Heal character (increases HP, not exceeding max_hp).

        Args:
            healing: Amount of healing
        """
        self.hp = min(self.max_hp, self.hp + healing)

    def is_alive(self) -> bool:
        """Check if character is alive (HP > 0)."""
        return self.hp > 0

    def is_conscious(self) -> bool:
        """Check if character is conscious (HP > 0 and not unconscious)."""
        return self.hp > 0 and "unconscious" not in [c.lower() for c in self.conditions]

    def add_condition(self, condition: str):
        """Add a condition if not already present."""
        if condition not in self.conditions:
            self.conditions.append(condition)

    def remove_condition(self, condition: str):
        """Remove a condition if present."""
        if condition in self.conditions:
            self.conditions.remove(condition)

    def has_condition(self, condition: str) -> bool:
        """Check if character has a specific condition."""
        return condition in self.conditions
