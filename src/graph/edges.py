"""
Conditional Edge Routing Logic for Weather-Advisory State Machine
"""
import logging
from src.models.state import AgentState

logger = logging.getLogger("weather_bot.edges")


def route_after_extraction(state: AgentState) -> str:
    """
    Branch 1: Evaluates parsed user query and context.
    - If adversarial injection attempt -> adversarial_fallback_node
    - If greeting -> greeting_node
    - If no location specified/inferred -> location_fallback_node
    - If valid location present -> fetch_weather_node
    """
    entities = state.get("extracted_entities", {})
    
    if entities.get("is_adversarial", False):
        logger.info("Routing to adversarial_fallback_node")
        return "adversarial_fallback_node"

    # Check for greeting intents when no specific location/activity is queried
    query = (state.get("user_query") or state.get("user_input") or "").strip().lower()
    cleaned_query = "".join(c for c in query if c.isalnum() or c.isspace()).strip()
    greetings = {"hi", "hello", "hey", "hii", "hiii", "namaste", "howdy", "greetings", "sup", "yo"}
    greeting_phrases = ["good morning", "good afternoon", "good evening", "good night", "namaste"]

    is_greeting = (
        cleaned_query in greetings
        or any(cleaned_query.startswith(g) for g in ["hi ", "hello ", "hey ", "hii ", "hiii ", "howdy "])
        or any(phrase in cleaned_query for phrase in greeting_phrases)
    )

    if is_greeting and not entities.get("location_name") and not entities.get("activity"):
        logger.info("Routing to greeting_node")
        return "greeting_node"

    if not entities.get("location_name"):
        logger.info("Routing to location_fallback_node (Missing location)")
        return "location_fallback_node"

    logger.info("Routing to fetch_weather_node")
    return "fetch_weather_node"


def route_after_weather(state: AgentState) -> str:
    """
    Branch 2: Evaluates result of Open-Meteo weather API call.
    - If location failed geocoding -> location_fallback_node
    - If weather API down / network error -> weather_error_fallback_node
    - If weather successfully retrieved -> match_sop_node
    """
    loc_status = state.get("location_status", "valid")
    weather_status = state.get("weather_status", "success")
    fallback_type = state.get("fallback_type", "NONE")

    if fallback_type == "LOCATION_NOT_FOUND" or loc_status == "unresolved":
        logger.info("Routing to location_fallback_node (Geocoding failed)")
        return "location_fallback_node"

    if fallback_type == "WEATHER_API_DOWN" or weather_status == "fetch_error" or not state.get("weather_data"):
        logger.info("Routing to weather_error_fallback_node")
        return "weather_error_fallback_node"

    logger.info("Routing to match_sop_node")
    return "match_sop_node"


def route_after_sop_matching(state: AgentState) -> str:
    """
    Branch 3: Evaluates policy match results.
    - If no SOP matched the condition/activity -> no_guidance_fallback_node
    - If one or more SOPs matched -> generate_advisory_node
    """
    matched = state.get("matched_sops", [])
    fallback_type = state.get("fallback_type", "NONE")

    if not matched or fallback_type == "NO_SOP_GUIDANCE":
        logger.info("Routing to no_guidance_fallback_node (No matching policy)")
        return "no_guidance_fallback_node"

    logger.info(f"Routing to generate_advisory_node ({len(matched)} SOPs matched)")
    return "generate_advisory_node"
