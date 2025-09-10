 
from typing import List

from langgraph.graph import MessagesState
from typing import Literal
from src.prompts.planner_model import Plan
from src.rag import Resource
from pydantic import BaseModel, Field
from typing import List,TypedDict,Annotated
import operator


class FinalEvaluationReport(BaseModel):
    library_name: str
    scores: int
    justification: str

class FinalEvaluationReports(BaseModel):
    final_ranked_list: List[FinalEvaluationReport]

class State(MessagesState):
    """State for the agent system, extends MessagesState with next field."""

    # Runtime Variables
    locale: str = "en-US"
    observations: list[str] = []
    resources: list[Resource] = []
    plan_iterations: int = 0
    current_plan: Plan | str = None
    final_report: str = ""
    auto_accepted_plan: bool = True

    brief_description_results: str = None
    source_library: str = None

    struct_results: str = None
    function_results: str = None
    update_results: str = None

    candidates: list[str] = []

    all_found_recommendations: Annotated[list, operator.add] = []

    agent_reports: Annotated[list, operator.add] = []
    aggregated_research_text: str = None
    analysis_tasks: list[dict] = []
    task: dict[str, any] = None

    scored_recommendations: Annotated[list, operator.add] = []
    ranked_recommendations: list[dict] = Field(default_factory=list)

    # enable_brief_description: bool = True