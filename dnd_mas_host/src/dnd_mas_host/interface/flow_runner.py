"""
Flow runner module for executing HostFlow in a background thread.

This module provides the background thread function that executes
the CrewAI HostFlow with GUI communication via thread-safe queues.
"""

import queue
import threading
import traceback
import copy
from typing import Dict

from ..main import HostFlow, UserCancelledActionException, FlowShutdownException
from .message_types import MessageType, create_message


def run_flow_in_thread(
    to_flow_queue: queue.Queue,
    from_flow_queue: queue.Queue,
    shutdown_event: threading.Event
):
    """
    Execute HostFlow in background thread with GUI communication.

    This function runs in a separate thread and:
    1. Waits for START_FLOW messages from GUI
    2. Executes HostFlow.kickoff() with GUI queues
    3. Sends results/errors back to GUI
    4. Handles shutdown gracefully

    Args:
        to_flow_queue: Queue receiving messages from GUI
        from_flow_queue: Queue sending messages to GUI
        shutdown_event: Threading event for clean shutdown signaling

    Thread Safety:
        - All communication via thread-safe queues
        - Uses deep copy for state extraction
        - Responds to shutdown_event for clean termination
    """
    print("[FlowThread] Starting flow thread")

    # Send ready signal to GUI
    from_flow_queue.put(create_message(
        MessageType.FLOW_READY,
        {"message": "Flow thread initialized and ready"}
    ))

    while not shutdown_event.is_set():
        try:
            # Wait for messages from GUI (1-second timeout for responsiveness)
            try:
                msg = to_flow_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            msg_type = msg.get("type")

            # Handle shutdown request
            if msg_type == MessageType.SHUTDOWN:
                print("[FlowThread] Received shutdown signal")
                break

            # Handle flow start request
            if msg_type == MessageType.START_FLOW:
                print(f"[FlowThread] Starting flow with prompt: {msg['data'].get('prompt', '')[:50]}...")

                try:
                    # Create HostFlow with GUI queues
                    dnd_flow = HostFlow(gui_queues={
                        "to_flow": to_flow_queue,
                        "from_flow": from_flow_queue
                    })

                    # Set initial state from GUI
                    dnd_flow.state.prompt_text = msg["data"]["prompt"]
                    dnd_flow.state.current_venue = msg["data"].get("venue", "Town Square")
                    dnd_flow.state.current_stage = msg["data"].get("stage", "Arrival and Investigation")

                    # Execute flow (may block at difficulty check waiting for user roll)
                    result = dnd_flow.kickoff()

                    print(result)
                    
                    # Extract state with deep copy to avoid shared references
                    state_snapshot = copy.deepcopy({
                        "narrative": result.final_output,
                        "hp": result.character_hp,
                        "max_hp": result.character_max_hp,
                        "venue": result.current_venue,
                        "stage": result.current_stage
                    })

                    # Send narrative to GUI
                    from_flow_queue.put(create_message(
                        MessageType.DISPLAY_NARRATIVE,
                        state_snapshot
                    ))

                    print("[FlowThread] Flow completed successfully")

                except UserCancelledActionException:
                    # User cancelled action - just wait for next prompt
                    print("[FlowThread] User cancelled action, waiting for new prompt")
                    continue

                except FlowShutdownException:
                    # Flow shutdown requested
                    print("[FlowThread] Flow shutdown requested")
                    break

                except Exception as e:
                    # Flow execution error
                    error_msg = str(e)
                    error_trace = traceback.format_exc()
                    print(f"[FlowThread] Flow error: {error_msg}")
                    print(error_trace)

                    from_flow_queue.put(create_message(
                        MessageType.FLOW_ERROR,
                        {
                            "error": error_msg,
                            "traceback": error_trace
                        }
                    ))

        except Exception as e:
            # Catch-all for unexpected thread errors
            print(f"[FlowThread] Unexpected thread error: {e}")
            traceback.print_exc()

            from_flow_queue.put(create_message(
                MessageType.FLOW_ERROR,
                {
                    "error": f"Thread error: {str(e)}",
                    "traceback": traceback.format_exc()
                }
            ))

    print("[FlowThread] Flow thread exiting")
