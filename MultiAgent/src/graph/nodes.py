 
import json
import logging
import os
import re
from typing import Annotated, Literal
from langchain.chains.summarize import load_summarize_chain
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.types import Command, interrupt
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_core.messages import AIMessage
from loguru import logger
from src.agents import create_agent
from src.tools.search import LoggedTavilySearch
from src.tools import (
    crawl_tool,
    get_web_search_tool,
    get_retriever_tool,
    python_repl_tool,
)
from src.config.agents import AGENT_LLM_MAP
from src.config.configuration import Configuration
from src.llms.llm import get_llm_by_type
from src.prompts.planner_model import Plan, StepType
from src.prompts.template import apply_prompt_template
from src.utils.json_utils import repair_json_output
from src.utils.cache_utils import save_to_cache
from .types import State, FinalEvaluationReport, FinalEvaluationReports
from ..config import SELECTED_SEARCH_ENGINE, SearchEngine
import operator
import csv
import os
from pathlib import Path

from ..tools.github import get_github_issue, read_github_file
from ..tools.load_recommend_results import load_and_prepare_candidates

logger = logging.getLogger(__name__)


@tool
def handoff_to_planner(
    task_title: Annotated[str, "The title of the task to be handed off."],
    locale: Annotated[str, "The user's detected language locale (e.g., en-US, zh-CN)."],
):
    """Handoff to planner agent to do plan."""
    # This tool is not returning anything: we're just using it
    # as a way for LLM to signal that it needs to hand off to planner agent
    return

def brief_description_node(state: State, config: RunnableConfig) -> Command[Literal["planner"]]:
    logger.info("brief_description node is running.")
    messages = apply_prompt_template("brief_description", state)
    configurable = Configuration.from_runnable_config(config)

    library_name = state["messages"][-1].content

    candidate_libraries = load_and_prepare_candidates(library_name)

    response=get_library_brief(library_name)
    locale = state.get("locale", "en-US")
    return Command(
        update={
            "brief_description_results": json.dumps(
                response, ensure_ascii=False
            ),
            "locale": locale,
            "source_library":library_name,
            "candidates":candidate_libraries
        },
        goto="planner",
    )




def planner_node(
    state: State, config: RunnableConfig
) -> Command[Literal["research_team","aggregator"]]:
    """Planner node that generate the full plan."""
    logger.info("Planner generating full plan")
    configurable = Configuration.from_runnable_config(config)
    plan_iterations = state["plan_iterations"] if state.get("plan_iterations", 0) else 0
    messages = apply_prompt_template("planner", state, configurable)
    candidates=state.get("candidates",[])
    if (
        plan_iterations == 0
        and state.get("brief_description_results")
    ):
        messages += [
            {
                "role": "user",
                "content": (
                    "brief_description of user query:\n"
                    + state["brief_description_results"]
                    + "\n"
                ),
            }
        ]
    candidates_message= f"Candiate Library Name:\n\n {candidates}"
    messages.append(HumanMessage(content=candidates_message))
    llm = get_llm_by_type(AGENT_LLM_MAP["planner"]).with_structured_output(
        Plan,
        method="json_mode",
    )


    if plan_iterations >= configurable.max_plan_iterations:
        return Command(goto="aggregator")
    full_response = ""
    if AGENT_LLM_MAP["planner"] == "reasoning":
        response = llm.invoke(messages)
        full_response = response.model_dump_json(indent=4, exclude_none=True)
    else:
        response = llm.stream(messages)
        for chunk in response:
            if hasattr(chunk, 'content'):
                full_response += chunk.content
    logger.debug(f"Current state messages: {state['messages']}")
    logger.info(f"Planner response: {full_response}")
    try:
        curr_plan = json.loads(repair_json_output(full_response))
    except json.JSONDecodeError:
        logger.warning("Planner response is not a valid JSON")
        if plan_iterations > 0:
            return Command(goto="aggregator")
        else:
            return Command(goto="__end__")
    if curr_plan.get("has_enough_context"):
        logger.info("Planner response has enough context.")
        new_plan = Plan.model_validate(curr_plan)
        return Command(
            update={
                "messages": [AIMessage(content=full_response, name="planner")],
                "current_plan": new_plan,
            },
            goto="aggregator",
        )
    return Command(
        update={
            "messages": [AIMessage(content=full_response, name="planner")],
            "current_plan": Plan.model_validate(curr_plan),
        },
        goto="research_team",
    )



def research_team_node(state: State):
    """Research team node that collaborates on tasks."""
    logger.info("Research team is collaborating on tasks.")
    pass

async def _execute_agent_step(
    state: State, agent, agent_name: str
) -> Command[Literal["research_team"]]:
    """Helper function to execute a step using the specified agent."""
    current_plan = state.get("current_plan")
    observations = state.get("observations", [])

    # Find the first unexecuted step
    current_step = None
    completed_steps = []
    for step in current_plan.steps:
        if not step.execution_res:
            current_step = step
            break
        else:
            completed_steps.append(step)

    if not current_step:
        logger.warning("No unexecuted step found")
        return Command(goto="research_team")

    logger.info(f"Executing step: {current_step.title}, agent: {agent_name}")


    source_lib_info = ""
    source_lib_info = state.get("brief_description_results")

    target_list_str = "\n- ".join(current_step.target_libraries)

    # Prepare the input for the agent with completed steps info
    agent_input = {
        "messages": [
            HumanMessage(
                content=f"""
                        {source_lib_info}# Current Task\n\n
                        ## Title\n\n{current_step.title}\n\n
                        ## Description\n\n{current_step.description}\n\n
                        ## Target Libraries to Investigate\n\n- {target_list_str}
                        ## Locale\n\n{state.get('locale', 'en-US')}
                        """
            )
        ]
    }

    # Add citation reminder for researcher agent
    # Invoke the agent
    default_recursion_limit = 25
    try:
        env_value_str = os.getenv("AGENT_RECURSION_LIMIT", str(default_recursion_limit))
        parsed_limit = int(env_value_str)

        if parsed_limit > 0:
            recursion_limit = parsed_limit
            logger.info(f"Recursion limit set to: {recursion_limit}")
        else:
            logger.warning(
                f"AGENT_RECURSION_LIMIT value '{env_value_str}' (parsed as {parsed_limit}) is not positive. "
                f"Using default value {default_recursion_limit}."
            )
            recursion_limit = default_recursion_limit
    except ValueError:
        raw_env_value = os.getenv("AGENT_RECURSION_LIMIT")
        logger.warning(
            f"Invalid AGENT_RECURSION_LIMIT value: '{raw_env_value}'. "
            f"Using default value {default_recursion_limit}."
        )
        recursion_limit = default_recursion_limit

    logger.info(f"Agent input: {agent_input}")
    result = await agent.ainvoke(
        input=agent_input, config={"recursion_limit": recursion_limit}
    )

    # Process the result
    response_content = result["messages"][-1].content
    logger.debug(f"{agent_name.capitalize()} full response: {response_content}")

    # Update the step with the execution result
    current_step.execution_res = response_content
    logger.info(f"Step '{current_step.title}' execution completed by {agent_name}")


    update_data = {
        "observations": observations + [response_content],
    }
    if agent_name == "struct":
        update_data["struct_results"] = response_content
    elif agent_name == "function":
        update_data["function_results"] = response_content
    elif agent_name == "update":
        update_data["update_results"] = response_content


    update_data["messages"] = [
        HumanMessage(content=response_content, name=agent_name)
    ]
    return Command(
        update=update_data,
        goto="research_team",
    )


async def _setup_and_execute_agent_step(
    state: State,
    config: RunnableConfig,
    agent_type: str,
    default_tools: list,
) -> Command[Literal["research_team"]]:
    """Helper function to set up an agent with appropriate tools and execute a step.

    This function handles the common logic for both researcher_node and coder_node:
    1. Configures MCP servers and tools based on agent type
    2. Creates an agent with the appropriate tools or uses the default agent
    3. Executes the agent on the current step

    Args:
        state: The current state
        config: The runnable config
        agent_type: The type of agent ("researcher" or "coder")
        default_tools: The default tools to add to the agent

    Returns:
        Command to update state and go to research_team
    """
    configurable = Configuration.from_runnable_config(config)
    mcp_servers = {}
    enabled_tools = {}

    # Extract MCP server configuration for this agent type
    if configurable.mcp_settings:
        for server_name, server_config in configurable.mcp_settings["servers"].items():
            if (
                server_config["enabled_tools"]
                and agent_type in server_config["add_to_agents"]
            ):
                mcp_servers[server_name] = {
                    k: v
                    for k, v in server_config.items()
                    if k in ("transport", "command", "args", "url", "env")
                }
                for tool_name in server_config["enabled_tools"]:
                    enabled_tools[tool_name] = server_name

    # Create and execute agent with MCP tools if available
    if mcp_servers:
        async with MultiServerMCPClient(mcp_servers) as client:
            loaded_tools = default_tools[:]
            for tool in client.get_tools():
                if tool.name in enabled_tools:
                    tool.description = (
                        f"Powered by '{enabled_tools[tool.name]}'.\n{tool.description}"
                    )
                    loaded_tools.append(tool)
            agent = create_agent(agent_type, agent_type, loaded_tools, agent_type)
            return await _execute_agent_step(state, agent, agent_type)
    else:
        # Use default tools if no MCP servers are configured
        agent = create_agent(agent_type, agent_type, default_tools, agent_type)
        return await _execute_agent_step(state, agent, agent_type)



async def struct_node(
    state: State, config: RunnableConfig
) -> Command[Literal["research_team"]]:
    """Struct node that do research"""
    logger.info("Struct node is researching.")
    configurable = Configuration.from_runnable_config(config)
    tools = [get_web_search_tool(configurable.max_search_results), crawl_tool]
    github_tools = [read_github_file, get_github_issue]
    tools.extend(github_tools)
    retriever_tool = get_retriever_tool(state.get("resources", []))
    if retriever_tool:
        tools.insert(0, retriever_tool)
    logger.info(f"Researcher tools: {tools}")
    return await _setup_and_execute_agent_step(
        state,
        config,
        "struct",
        tools,
    )


async def function_node(
    state: State, config: RunnableConfig
) -> Command[Literal["research_team"]]:
    """Function node that do code analysis."""
    logger.info("Function node is coding.")
    configurable = Configuration.from_runnable_config(config)
    tools = [get_web_search_tool(configurable.max_search_results), crawl_tool]
    github_tools = [read_github_file, get_github_issue]
    tools.extend(github_tools)
    retriever_tool = get_retriever_tool(state.get("resources", []))
    if retriever_tool:
        tools.insert(0, retriever_tool)
    logger.info(f"Researcher tools: {tools}")
    return await _setup_and_execute_agent_step(
        state,
        config,
        "function",
        tools,
    )

async def update_node(
    state: State, config: RunnableConfig
) -> Command[Literal["research_team"]]:
    """Function node that do code analysis."""
    logger.info("Update node is coding.")
    configurable = Configuration.from_runnable_config(config)
    tools = [get_web_search_tool(configurable.max_search_results), crawl_tool]
    github_tools = [read_github_file, get_github_issue]
    tools.extend(github_tools)
    retriever_tool = get_retriever_tool(state.get("resources", []))
    if retriever_tool:
        tools.insert(0, retriever_tool)
    logger.info(f"Researcher tools: {tools}")
    return await _setup_and_execute_agent_step(
        state,
        config,
        "update",
        tools,
    )


def aggregator_node(state: State, config: RunnableConfig) -> Command[Literal["reporter"]]:
    logger.info("---Aggregator---")
    struct_summary = state.get("struct_results", "struct summary not exist")
    function_summary = state.get("function_results", "function summary not exist")
    update_summary = state.get("update_results", "update summary not exist")
    source_library = state.get("source_library")
    aggregated_text = f"""
struct_summary:{struct_summary}/n
function_summary:{function_summary}/n
update_summary:{update_summary}
"""
    if source_library and aggregated_text:
        save_to_cache(
            library_name=source_library,
            data={"deep_research_report": aggregated_text},
            cache_type="deep_research"
        )
    else:
        logger.error("error")
    logger.info("success")

    return Command(
        update={
            "aggregated_research_text": aggregated_text
        },
        goto="reporter"
    )



def reporter_node(state: State, config: RunnableConfig) -> dict[str, any]:
    logger.info("--- 💎  ---")
    source_library = state.get("source_library", "UNKNOWN")
    source_library_info = state.get("brief_description_results")

    aggregated_text = state.get("aggregated_research_text")
    context_threshold =24000
    if len(aggregated_text) > context_threshold:
        logger.info(f" ({len(aggregated_text)} > {context_threshold})，...")
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=context_threshold,
            chunk_overlap=200
        )
        docs = text_splitter.create_documents([aggregated_text])
        summarizer_llm = get_llm_by_type("basic")
        summary_chain = load_summarize_chain(llm=summarizer_llm, chain_type="map_reduce")
        summarized_text = summary_chain.invoke(docs).get("output_text", "")
        all_agent_reports = summarized_text
        logger.info(f" {len(all_agent_reports)}")
    else:
        logger.info("success")
        all_agent_reports = aggregated_text
    state = {
        "messages": [
            HumanMessage(
                f"# source_library_information\n\n{source_library_info}  # all_agent_reports\n\n{all_agent_reports} "
            )
        ],
        "locale": state.get("locale", "en-US"),
    }

    configurable = Configuration.from_runnable_config(config)
    messages = apply_prompt_template("reporter", state, configurable)

    list_of_reports = []
    final_reports_obj = None
    logger.info("...")
    if AGENT_LLM_MAP["reporter"] == "reasoning":
        evaluator_llm = get_llm_by_type("reasoning")
        response = evaluator_llm.invoke(messages)
        try:
            core_data_string = ""
            if hasattr(response, 'response_metadata') and 'generations' in response.response_metadata:
                core_data_string = response.response_metadata['generations'][0][0]['text']
            else:
                core_data_string = response.content

            logger.info(" Markdown...")
            match = re.search(r"```(?:json)?\s*([\s\S]+)```", core_data_string)
            if match:
                text_to_parse = match.group(1)
                logger.info("Markdown ")
            else:
                text_to_parse = core_data_string
            cleaned_string = text_to_parse.strip()
            if cleaned_string.startswith('{') and cleaned_string.endswith(']'):
                logger.info("[INFO]  '[' fix...")
                fixed_string = '[' + cleaned_string
            else:
                fixed_string = cleaned_string

            parsed_data = json.loads(fixed_string)

            if isinstance(parsed_data, list):
                final_reports_obj = FinalEvaluationReports(final_ranked_list=parsed_data)
                list_of_reports = final_reports_obj.final_ranked_list
            elif isinstance(parsed_data, dict):
                final_reports_obj = FinalEvaluationReports(final_ranked_list=[parsed_data])
                list_of_reports = final_reports_obj.final_ranked_list

            logger.info(f"✅  {len(list_of_reports)} ")

        except Exception as e:
            logger.error(f"⚠️ {e}")
            list_of_reports = []
            final_reports_obj = None
    else:
        logger.info(f"pass")
        return {"final_report": final_reports_obj.model_dump() if final_reports_obj else {"final_ranked_list": []}}
    output_csv_path = Path("experiment_results.csv")
    csv_fieldnames = [
        "source_library",
        "predicted_target_library",
        "scores",
        "justification"
    ]
    if list_of_reports:
        for rec in list_of_reports:
            csv_row = {
                "source_library": source_library,
                "predicted_target_library": rec.library_name,
                "scores": rec.scores,
                "justification": rec.justification
            }
            _append_to_csv(output_csv_path, csv_row, csv_fieldnames)

        logger.info(f"✅  {len(list_of_reports)} ")
    else:
        logger.info("⚠️ ")
    return {"final_report": final_reports_obj.model_dump() if final_reports_obj else {"final_ranked_list": []}}


def _append_to_csv(filepath: Path, row_data: dict, fieldnames: list):
    try:
        file_exists = filepath.exists()
        with open(filepath, mode='a', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)

            if not file_exists:
                writer.writeheader()

            writer.writerow(row_data)
    except Exception as e:
        logger.error(f"CSV  {filepath} : {e}")



def get_library_brief(library_name: str) -> dict | None:
    base_path = r"filepath"

    folder_name = library_name.replace('.', '_').replace(':', '__')
    json_file_name = "biref_description.json"

    file_path = os.path.join(base_path, folder_name, json_file_name)

    if not os.path.exists(file_path):
        print(f"❌  {file_path}")
        return None

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            response = json.load(f)
        print(f"✅ {library_name})
        return response
    except json.JSONDecodeError:
        print(f"❌ {file_path}")
        return None
    except Exception as e:
        print(f"❌ {e}")
        return None
