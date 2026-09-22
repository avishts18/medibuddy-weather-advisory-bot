"""
AgentState TypedDict for LangGraph state machine
"""
from typing import TypedDict, List, Dict, Any, Optional
from langchain_core.messages import BaseMessage


class ExtractedEntities(TypedDict, total=False):
    location_name: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    activity: Optional[str]
    demographics: Optional[List[str]]
    timeframe: Optional[str]
    is_adversarial: bool
    adversarial_reason: Optional[str]
    confidence: float


class AgentState(TypedDict):
    """
    Main state schema representing the lifecycle of an interaction turn in LangGraph.
    Carried across multi-turn session memory.
    """
    # Conversational History & Session
    messages: List[BaseMessage]
    session_id: str
    user_query: str

    # Turn Extracted Entities (retained/updated across turns)
    extracted_entities: ExtractedEntities

    # Location & Weather Telemetry (JSON-serializable dict structures)
    location_info: Optional[Dict[str, Any]]
    location_status: str # "valid", "unresolved", "api_error"
    weather_data: Optional[Dict[str, Any]]
    weather_status: str # "success", "fetch_error", "skipped"

    # SOP Evaluation & Decision Engine
    matched_sops: List[Dict[str, Any]]
    primary_sop: Optional[Dict[str, Any]]
    is_synoptic_event_active: bool

    # Routing & Fallback Diagnostics
    fallback_type: str # "NONE", "LOCATION_NOT_FOUND", "WEATHER_API_DOWN", "NO_SOP_GUIDANCE", "ADVERSARIAL_INJECTION"
    fallback_message: Optional[str]

    # Final Grounded Output
    final_response: str
    citations: List[str]
    execution_trace: List[str]
