"""
Global configuration constants for the D&D MAS Host system.

This module contains shared configuration values used across different crews and agents.
"""

# LLM Configuration
# Manager LLM used for hierarchical process coordination in Judge and Narrator crews
# Using gpt-5-mini-2025-08-07 which supports both:
# 1. Tool calling (delegation) required for hierarchical process
# 2. Structured outputs (json_schema) required for Pydantic model conversion
MANAGER_LLM = "gpt-5-mini-2025-08-07"

# Agent Execution Control
# See: https://docs.crewai.com/en/concepts/agents#execution-control
# These values control how agents behave during task execution

# Maximum iterations before agent gives best answer (default: 25 in CrewAI)
# Lower values = faster execution but potentially less thorough
# Higher values = more thorough but slower and higher API costs
MAX_ITER = 3

# Maximum execution time per task in seconds (default: None)
# Set to prevent agents from running indefinitely
# None = no timeout
MAX_EXECUTION_TIME = 100  # 3 minutes per task

# Maximum requests per minute for API rate limiting (default: None)
# Controls how many LLM API calls can be made per minute
# Useful for managing costs and staying within API limits
# None = no rate limiting
MAX_RPM = None

# Maximum retry attempts when an error occurs (default: 2)
# How many times to retry a failed task before giving up
MAX_RETRY_LIMIT = 1

# Blackboard Logging
# When True, all blackboard read/write operations are logged to console
# Useful for debugging state changes in the message-passing architecture
ENABLE_BLACKBOARD_LOGGING = True
