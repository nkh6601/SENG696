# D&D Multi-Agent System - GUI Interface

This directory contains the PySimpleGUI-based interface for the D&D Multi-Agent System.

## Architecture

The GUI interface runs in a two-thread architecture:

- **Main Thread (GUI)**: Runs PySimpleGUI event loop, handles user input/output
- **Background Thread (Flow)**: Executes CrewAI HostFlow with AI agent orchestration

Communication between threads uses thread-safe `queue.Queue` objects.

## Files

- **`gui_interface.py`**: Main GUI class (`DnDGUIInterface`) with PySimpleGUI window and event handling
- **`flow_runner.py`**: Background thread function that executes HostFlow
- **`message_types.py`**: Message protocol definitions for inter-thread communication
- **`__init__.py`**: Package initialization

## Prerequisites

1. **MongoDB**: Must be running locally on `localhost:27017`
   - Start MongoDB via Docker Desktop or local MongoDB Community Server
   - The GUI will check connection on startup and show error if unavailable

2. **Dependencies**: Install via `crewai install` (includes PySimpleGUI)

3. **Environment Variables**: Configure `.env` file with:
   ```
   MODEL=gemini/gemini-2.0-flash-lite-001
   GEMINI_API_KEY=<your-api-key>
   ```

## Running the GUI

### Option 1: Via project script (recommended)
```bash
python -m dnd_mas_host.interface.gui_interface
```

### Option 2: Via crewai command (after installation)
```bash
crewai gui
```

## Using the GUI

### Startup
1. The GUI checks MongoDB connection on startup
2. If successful, the main window opens with a welcome message
3. The background thread initializes and signals "Ready for action"

### Game Loop
1. **Enter Action**: Type your character's action in the "Your Action" input field
2. **Submit**: Click "Submit" or press Enter to send the action
3. **Validation**: The Narrator agent validates your prompt
   - If invalid: Clarification message appears in chat
   - If valid: Difficulty check is requested
4. **Difficulty Check**:
   - The DC (Difficulty Class) is displayed
   - Click "Roll d20" to roll and continue
   - Or click "Cancel Action" to modify your prompt
5. **Roll Result**: Your d20 roll is displayed
6. **Narrative**: The final narrative appears in the chat log
7. **Repeat**: Enter your next action

### GUI Elements

- **Character Status**: Shows HP and current location
- **Adventure Log**: Chat history with labeled messages
  - `[NARRATOR]`: Story narration
  - `[YOU]`: Your actions
  - `[SYSTEM]`: System messages (rolls, cancellations)
  - `[NPC NAME]`: NPC dialogue
- **Action Check Panel**: Shows difficulty check when needed
- **Your Action**: Input field for typing actions
- **Status Bar**: Current system status

### Shutdown
- Close the window or click Exit
- The GUI will:
  1. Signal the background thread to shut down
  2. Wait for thread termination (5-second timeout)
  3. Close MongoDB connection
  4. Exit the application

## Message Protocol

The GUI communicates with the Flow thread via standardized messages:

### GUI → Flow Messages
- `START_FLOW`: Begin flow execution with user prompt
- `ROLL_D20`: User rolled d20, continue flow
- `CANCEL_ACTION`: User cancelled action
- `SHUTDOWN`: Terminate thread

### Flow → GUI Messages
- `FLOW_READY`: Thread initialized
- `VALIDATION_ERROR`: Invalid prompt, display clarification
- `REQUEST_DIFFICULTY_CHECK`: Display DC and await roll
- `DISPLAY_NARRATIVE`: Show final narrative
- `FLOW_ERROR`: Exception occurred

## Thread Safety

- All inter-thread communication uses `queue.Queue` (inherently thread-safe)
- GUI widgets are ONLY updated from the main thread (PySimpleGUI requirement)
- State is deep-copied when passing between threads to avoid shared references
- Shutdown uses `threading.Event` for clean signaling

## Error Handling

### MongoDB Connection Error
- Displayed as popup on startup
- Application exits if connection fails

### Flow Execution Error
- Displayed as popup during gameplay
- GUI resets to ready state
- User can try a different action

### Validation Error
- Displayed as Narrator message in chat
- GUI re-enables input for new prompt
- No popup (conversational feedback)

## Troubleshooting

### MongoDB Connection Failed
**Symptom**: Popup error on startup
**Solution**:
- Ensure MongoDB is running on Docker Desktop
- Or start local MongoDB: `mongod --dbpath <path>`
- Verify connection: `mongo --eval "db.version()"`

### GUI Freezes
**Symptom**: Window not responding
**Solution**:
- This is expected during flow execution (steps 1-11)
- Flow execution can take 20-60 seconds depending on LLM response time
- The GUI will become responsive again after narrative is displayed

### Flow Thread Doesn't Terminate
**Symptom**: Warning message on shutdown
**Solution**:
- The thread is daemon=True so it will auto-terminate
- Application will still close normally
- No action needed

### Import Errors
**Symptom**: `ModuleNotFoundError: No module named 'PySimpleGUI'`
**Solution**: Run `crewai install` to install dependencies

## Development Notes

### Modifying the GUI Layout
Edit `gui_interface.py` → `initialize_gui()` method

### Changing Message Protocol
Edit `message_types.py` → Add new `MessageType` enum values

### Modifying Flow Integration
Edit `main.py` → `perform_check()` method for difficulty check logic
Edit `main.py` → `request_clarification()` method for validation errors

### Testing Without GUI
The CLI mode still works - just run:
```bash
crewai run
```

The HostFlow automatically detects if `gui_queues` is None and falls back to auto-rolling d20.

## Future Enhancements

Potential improvements (out of current scope):
- Save/load game state to MongoDB
- Combat tracker with initiative/spell slots
- Map visualization window
- Streaming narrative (word-by-word display)
- Voice input via speech-to-text
- Async flow execution (if CrewAI adds support)
