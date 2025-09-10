 

from langgraph.graph import StateGraph, START, END
from langgraph.types import Send
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.base import BaseCheckpointSaver
from src.prompts.planner_model import StepType
from .types import State
from loguru import logger
from .nodes import (
    brief_description_node,
    planner_node,
    struct_node,
    function_node,
    update_node,
    aggregator_node,
    reporter_node,
    research_team_node,
)

def _build_base_graph() -> StateGraph:

    builder = StateGraph(State)
    builder.add_node("brief_description", brief_description_node)
    builder.add_node("planner", planner_node)
    builder.add_node("struct", struct_node)
    builder.add_node("function", function_node)
    builder.add_node("update", update_node)
    builder.add_node("research_team", research_team_node)
    builder.add_node("aggregator", aggregator_node)
    builder.add_node("reporter", reporter_node)

    builder.set_entry_point("brief_description")
    builder.add_conditional_edges(
        "research_team",
        continue_to_running_research_team,
        ["aggregator", "struct", "function","update"],
    )

    builder.add_edge("aggregator", "reporter")
    builder.add_edge("reporter", END)
    return builder


def continue_to_running_research_team(state: State):
    current_plan = state.get("current_plan")
    if not current_plan or not current_plan.steps:
        return "aggregator"
    if all(step.execution_res for step in current_plan.steps):
        return "aggregator"
    for step in current_plan.steps:
        if not step.execution_res:
            break
    if step.step_type and step.step_type == StepType.STRUCT:
        return "struct"
    if step.step_type and step.step_type == StepType.FUNCTION:
        return "function"
    if step.step_type and step.step_type == StepType.UPDATE:
        return "update"
    return "aggregator"


def build_graph(checkpointer: BaseCheckpointSaver = None):
    builder = _build_base_graph()
    return builder.compile(checkpointer=checkpointer)


def build_graph_with_memory():
    memory = MemorySaver()
    return build_graph(checkpointer=memory)


graph = build_graph()