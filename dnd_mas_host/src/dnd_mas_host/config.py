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
