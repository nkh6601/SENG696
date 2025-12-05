"""
Test script to visualize the new 3-column GUI layout.
This script creates a standalone GUI window with sample data.
"""

import PySimpleGUI as sg


def create_test_window():
    """Create test window with sample data."""
    sg.theme('DarkBlue3')

    # Sample data
    player = "Thorin Oakenshield"
    player_class = "Fighter (Level 5)"
    character_hp = 45
    character_max_hp = 50
    current_venue = "Town Square - Central Market"
    current_stage = "Chapter 1: The Slime Invasion"
    character_skills = ["Athletics", "Intimidation", "Survival", "Perception"]
    character_items = ["Longsword +1", "Shield", "Plate Armor", "Healing Potion (x3)", "Rations (5 days)", "Rope (50 ft)"]

    # Sample NPCs
    sample_npcs = [
        {
            "name": "Captain Miranda",
            "hp": 30,
            "max_hp": 30,
            "status": "Healthy",
            "description": "A seasoned town guard captain with a stern expression and battle-worn armor."
        },
        {
            "name": "Gelatinous Blob",
            "hp": 15,
            "max_hp": 25,
            "status": "Wounded",
            "description": "A pulsating slime creature that oozes acid from its translucent form."
        }
    ]

    # Left Column - Player Character Information
    pc_column = [
        [sg.Text("Player Character", font=("Helvetica", 12, "bold"))],
        [sg.Frame("Character Info", [
            [sg.Text(f"Name: {player}", key="-PLAYER-NAME-", size=(25, 1))],
            [sg.Text(f"Class: {player_class}", key="-PLAYER-CLASS-", size=(25, 1))],
            [sg.Text(f"HP: {character_hp}/{character_max_hp}", key="-HP-", size=(25, 1))],
            [sg.HorizontalSeparator()],
            [sg.Text(f"Location: {current_venue}", key="-VENUE-", size=(25, 2))],
            [sg.Text(f"Stage: {current_stage}", key="-STAGE-", size=(25, 2))],
        ])],
        [sg.Frame("Skills", [
            [sg.Multiline(
                default_text=", ".join(character_skills),
                key="-SKILLS-",
                size=(25, 4),
                disabled=True,
                font=("Courier", 9),
                background_color="#1E1E1E",
                text_color="#FFFFFF"
            )]
        ])],
        [sg.Frame("Inventory", [
            [sg.Multiline(
                default_text=", ".join(character_items),
                key="-ITEMS-",
                size=(25, 8),
                disabled=True,
                font=("Courier", 9),
                background_color="#1E1E1E",
                text_color="#FFFFFF"
            )]
        ])],
    ]

    # Center Column - Chat and Input
    sample_narrative = """[YOU] I draw my sword and approach the slime creature cautiously.

[NARRATOR] As you draw your gleaming longsword, the gelatinous blob quivers and pulsates. Captain Miranda steps beside you, her own blade at the ready. "Be careful," she warns, "these things are more dangerous than they look."

The creature slowly oozes forward, leaving a trail of acidic slime that sizzles on the cobblestones. The townspeople have cleared the square, watching nervously from windows and doorways.

[YOU] I attempt to strike at its core with my sword!

[NARRATOR] Your blade arcs through the air with practiced precision, finding purchase in the creature's gelatinous form. The slime recoils, its translucent body rippling with the impact. Acidic droplets spray from the wound, narrowly missing your armor.

You've dealt significant damage, but the creature is still active and looks angry!"""

    center_column = [
        [sg.Text("Adventure Log", font=("Helvetica", 12, "bold"))],
        [sg.Frame("Narrative", [
            [sg.Multiline(
                default_text=sample_narrative,
                key="-CHAT-",
                size=(60, 30),
                autoscroll=True,
                disabled=True,
                font=("Courier", 10),
                background_color="#1E1E1E",
                text_color="#FFFFFF"
            )]
        ])],
        # Difficulty Check Panel (visible for demo)
        [sg.Frame("Action Check", [
            [sg.Text("Attempt to dodge the slime's counterattack", key="-ACTION-", size=(50, 1))],
            [
                sg.Text("Difficulty Check (DC): 14", key="-DC-", size=(20, 1)),
                sg.Button("Roll d20", key="-ROLL-"),
                sg.Text("You rolled: 16 (Success!)", key="-ROLL-RESULT-", size=(20, 1))
            ]
        ], key="-CHECK-FRAME-")],
        # User Input
        [sg.Frame("Your Action", [
            [
                sg.Input(
                    "I dodge and strike again!",
                    key="-PROMPT-INPUT-",
                    size=(40, 1),
                ),
                sg.Button("Submit", key="-SUBMIT-PROMPT-"),
                sg.Button("Cancel Action", key="-CANCEL-CHECK-")
            ]
        ])],
    ]

    # Right Column - NPC Information
    npc_text = ""
    for npc in sample_npcs:
        name = npc.get("name", "Unknown")
        hp = npc.get("hp", "?")
        max_hp = npc.get("max_hp", "?")
        status = npc.get("status", "")
        description = npc.get("description", "")

        npc_text += f"{'=' * 23}\n"
        npc_text += f"{name}\n"
        npc_text += f"{'=' * 23}\n"
        npc_text += f"HP: {hp}/{max_hp}\n"
        if status:
            npc_text += f"Status: {status}\n"
        if description:
            desc_short = description[:50] + "..." if len(description) > 50 else description
            npc_text += f"{desc_short}\n"
        npc_text += "\n"

    npc_column = [
        [sg.Text("Non-Player Characters", font=("Helvetica", 12, "bold"))],
        [sg.Frame("NPCs in Area", [
            [sg.Multiline(
                default_text=npc_text.strip(),
                key="-NPC-STATUS-",
                size=(25, 35),
                disabled=True,
                font=("Courier", 9),
                background_color="#1E1E1E",
                text_color="#FFFFFF"
            )]
        ])],
    ]

    # Main Layout - Three Column Design
    layout = [
        # Title
        [sg.Text("D&D Multi-Agent System", font=("Helvetica", 16, "bold"), justification='center', expand_x=True)],
        # Three Columns
        [
            sg.Column(pc_column, vertical_alignment='top', element_justification='left'),
            sg.VerticalSeparator(),
            sg.Column(center_column, vertical_alignment='top', element_justification='center'),
            sg.VerticalSeparator(),
            sg.Column(npc_column, vertical_alignment='top', element_justification='right')
        ],
        # Status bar
        [sg.Text("Ready for action", key="-STATUS-", size=(120, 1), relief=sg.RELIEF_SUNKEN)]
    ]

    # Create window
    window = sg.Window(
        "D&D Adventure - Layout Test",
        layout,
        finalize=True,
        resizable=True,
        size=(1400, 900)
    )

    return window


def main():
    """Run the test GUI."""
    print("=" * 60)
    print("D&D Multi-Agent System - GUI Layout Test")
    print("=" * 60)
    print("\nDisplaying 3-column layout:")
    print("  LEFT: Player Character Information")
    print("  CENTER: Adventure Log & Input")
    print("  RIGHT: NPC Information")
    print("\nClose the window to exit.")
    print("=" * 60)

    window = create_test_window()

    # Event loop
    while True:
        event, values = window.read()

        if event in (sg.WIN_CLOSED, "Exit"):
            break

        if event == "-SUBMIT-PROMPT-":
            sg.popup("Submit button clicked!\nIn the real app, this would send the action to the game flow.", title="Demo")

        if event == "-ROLL-":
            sg.popup("Roll button clicked!\nIn the real app, this would perform a d20 roll.", title="Demo")

    window.close()
    print("\nTest completed!")


if __name__ == "__main__":
    main()
