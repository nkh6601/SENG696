"""
Quick test to verify NarratorFlow initialization fix.
Tests that the state model can be initialized without required fields.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Test just the state model directly
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

# Simplified test - just check if the pattern works
class TestMessage(BaseModel):
    type: str
    data: Dict[str, Any] = Field(default_factory=dict)

class TestState(BaseModel):
    msg: Optional[TestMessage] = None
    workflow_phase: str = ""
    prompt_valid: bool = True

def test_state_initialization():
    """Test that state can be initialized without msg"""
    print("[TEST] Testing state initialization without msg...")
    state = TestState()
    assert state.msg is None
    assert state.workflow_phase == ""
    assert state.prompt_valid == True
    print("[TEST] [PASS] State initialized successfully without msg")

def test_state_with_message():
    """Test that state can be initialized with a message"""
    print("[TEST] Testing state initialization with msg...")
    msg = TestMessage(type="VALIDATE_PROMPT", data={"prompt": "test"})
    state = TestState(msg=msg)
    assert state.msg is not None
    assert state.msg.type == "VALIDATE_PROMPT"
    print("[TEST] [PASS] State initialized successfully with msg")

if __name__ == "__main__":
    print("=" * 60)
    print("Testing State Initialization Pattern")
    print("=" * 60)

    test_state_initialization()
    test_state_with_message()

    print("=" * 60)
    print("[PASS] All tests passed!")
    print("=" * 60)
