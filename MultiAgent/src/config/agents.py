 

from typing import Literal

# Define available LLM types
LLMType = Literal["basic", "reasoning", "vision"]

# Define agent-LLM mapping
AGENT_LLM_MAP: dict[str, LLMType] = {
    "planner": "reasoning",
    "researcher": "basic",
    "brief_description": "basic",
    "struct": "basic",
    "function": "reasoning",
    "update": "basic",
    "reporter": "reasoning",
}
