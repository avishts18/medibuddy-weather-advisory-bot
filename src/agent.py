"""
High-Level Agent Interface for Weather-Advisory Support Bot
"""
import uuid
import logging
from typing import Dict, Any, Optional
from langchain_core.messages import HumanMessage

from src.graph.workflow import create_weather_advisory_graph

logger = logging.getLogger("weather_bot.agent")


class WeatherAdvisoryAgent:
    """
    Production-ready agent wrapper managing sessions, memory checkpointer,
    and invocation of the branched LangGraph state machine.
    """

    def __init__(self):
        self.graph = create_weather_advisory_graph()

    def process_query(
        self,
        query: str,
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Executes a single conversational turn within a given session context.
        Retains previous state (location, prior context) via LangGraph checkpointer.
        """
        sid = session_id or str(uuid.uuid4())
        config = {"configurable": {"thread_id": sid}}

        # Only pass the incremental turn delta so existing checkpoint state is preserved
        input_delta = {
            "user_query": query,
            "session_id": sid,
            "messages": [HumanMessage(content=query)],
            "execution_trace": [],
        }

        logger.info(f"Invoking WeatherAdvisoryAgent for session '{sid}' with query: \"{query}\"")
        result = self.graph.invoke(input_delta, config=config)

        return {
            "session_id": sid,
            "query": query,
            "response": result.get("final_response", ""),
            "citations": result.get("citations", []),
            "location": result.get("location_info"),
            "weather_data": result.get("weather_data"),
            "matched_sops": result.get("matched_sops", []),
            "primary_sop": result.get("primary_sop"),
            "fallback_type": result.get("fallback_type", "NONE"),
            "execution_trace": result.get("execution_trace", []),
            "extracted_entities": result.get("extracted_entities", {}),
        }
