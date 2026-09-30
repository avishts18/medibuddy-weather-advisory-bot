"""
LangGraph StateGraph Definition & Compilation
"""
from typing import Optional
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from src.models.state import AgentState
from src.graph.nodes import (
    extract_entities_node,
    greeting_node,
    fetch_weather_node,
    match_sop_node,
    generate_advisory_node,
    location_fallback_node,
    weather_error_fallback_node,
    no_guidance_fallback_node,
    adversarial_fallback_node,
)
from src.graph.edges import (
    route_after_extraction,
    route_after_weather,
    route_after_sop_matching,
)


def create_weather_advisory_graph(checkpointer: Optional[MemorySaver] = None):
    """
    Constructs and compiles the branched LangGraph workflow.
    Provides session persistence through LangGraph checkpointer.
    """
    workflow = StateGraph(AgentState)

    # 1. Register Nodes
    workflow.add_node("extract_entities", extract_entities_node)
    workflow.add_node("greeting", greeting_node)
    workflow.add_node("fetch_weather", fetch_weather_node)
    workflow.add_node("match_sop", match_sop_node)
    workflow.add_node("generate_advisory", generate_advisory_node)
    
    # Fallback & Fail-Safe Nodes
    workflow.add_node("location_fallback", location_fallback_node)
    workflow.add_node("weather_error_fallback", weather_error_fallback_node)
    workflow.add_node("no_guidance_fallback", no_guidance_fallback_node)
    workflow.add_node("adversarial_fallback", adversarial_fallback_node)

    # 2. Add Graph Connections & Branching Edges
    workflow.add_edge(START, "extract_entities")

    # Branch 1: After parsing user query
    workflow.add_conditional_edges(
        "extract_entities",
        route_after_extraction,
        {
            "adversarial_fallback_node": "adversarial_fallback",
            "greeting_node": "greeting",
            "location_fallback_node": "location_fallback",
            "fetch_weather_node": "fetch_weather"
        }
    )

    # Branch 2: After fetching weather data
    workflow.add_conditional_edges(
        "fetch_weather",
        route_after_weather,
        {
            "location_fallback_node": "location_fallback",
            "weather_error_fallback_node": "weather_error_fallback",
            "match_sop_node": "match_sop"
        }
    )

    # Branch 3: After SOP matching & conflict resolution
    workflow.add_conditional_edges(
        "match_sop",
        route_after_sop_matching,
        {
            "no_guidance_fallback_node": "no_guidance_fallback",
            "generate_advisory_node": "generate_advisory"
        }
    )

    # Terminal edges
    workflow.add_edge("greeting", END)
    workflow.add_edge("generate_advisory", END)
    workflow.add_edge("location_fallback", END)
    workflow.add_edge("weather_error_fallback", END)
    workflow.add_edge("no_guidance_fallback", END)
    workflow.add_edge("adversarial_fallback", END)

    # 3. Compile with Checkpointer for Multi-Turn Session Memory
    memory = checkpointer if checkpointer is not None else MemorySaver()
    app = workflow.compile(checkpointer=memory)
    return app
