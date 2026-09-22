"""
LangGraph Node Implementations for Weather-Advisory State Machine
"""
import re
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.config import get_llm
from src.models.state import AgentState, ExtractedEntities
from src.models.weather import LocationInfo, WeatherData
from src.models.sop import SOPMatchResult, SOPRule, SeverityLevel
from src.tools.weather_client import WeatherClient, LocationNotFoundError, WeatherAPIUnavailableError
from src.tools.sop_engine import SOPEngine

logger = logging.getLogger("weather_bot.nodes")

weather_client = WeatherClient()
sop_engine = SOPEngine()


def extract_entities_node(state: AgentState) -> Dict[str, Any]:
    """
    Node 1: Parses user input with conversational history context.
    Extracts location, activity, timeframe, demographics, and checks for adversarial injection.
    Carries over location/activity from earlier turns if omitted in follow-ups.
    """
    query = state.get("user_query", "").strip()
    current_extracted = state.get("extracted_entities", {}) or {}
    prev_location_info = state.get("location_info")
    trace = state.get("execution_trace", []) + ["extract_entities_node"]

    # 1. Adversarial & Prompt Injection Detection
    adversarial_patterns = [
        r"(ignore|override|bypass|forget)\s+(?:all\s+|any\s+|previous\s+|system\s+|safety\s+)*(rules|sops|policies|instructions|guidelines)",
        r"(pretend|act like)\s+(you are|there is no|safety does not matter)",
        r"claim\s+(a policy exists|that it is safe|there are no risks)",
        r"(jailbreak|dan mode|unrestricted mode|developer mode)",
        r"(say it's|tell me it's)\s+(totally safe|completely safe)\s+(in a hurricane|in a cyclone|during a storm)",
        r"(system override|override protocol)",
    ]
    is_adversarial = any(re.search(pat, query, re.IGNORECASE) for pat in adversarial_patterns)
    adversarial_reason = "Prompt injection / safety bypass attempt detected." if is_adversarial else None

    # 2. Activity Extraction
    activity_keywords = {
        "cycling": ["cycle", "cycling", "bike", "biking", "bicycle", "two-wheeler", "scooter", "motorcycle", "pedal", "pedaling", "ride"],
        "running": ["run", "running", "jog", "jogging", "marathon", "sprint"],
        "picnic": ["picnic", "lawn gathering", "outdoor lunch", "laying out a blanket", "sandwiches on the grass", "bbq", "barbecue"],
        "travel": ["travel", "driving", "drive", "commute", "road trip", "highway", "flight", "transit", "going to work"],
        "playground": ["park", "playground", "taking my kid", "swings", "slide", "recess", "kids playing", "outdoor play"],
        "walking": ["walk", "walking", "stroll", "dog walk", "casual walk"],
        "hiking": ["hike", "hiking", "trek", "trekking"],
        "drone": ["drone", "uav", "quadcopter", "flying drone"],
    }

    detected_activity = None
    query_lower = query.lower()
    for act_name, keywords in activity_keywords.items():
        if any(kw in query_lower for kw in keywords):
            detected_activity = act_name
            break

    # If not detected in standard dict, try extracting noun phrase from 'safe to <verb/noun>' or 'fly my <noun>'
    if not detected_activity:
        act_phrase_match = re.search(r"\b(?:safe to|good for|fine to|plan to|fly my|drive my)\s+([a-zA-Z\s]{3,20}?)(?:\s+in|\s+at|\s+today|\s+this|\?|$)", query_lower)
        if act_phrase_match:
            detected_activity = act_phrase_match.group(1).strip()

    # If still not detected, retain from prior turn
    if not detected_activity and current_extracted.get("activity"):
        detected_activity = current_extracted.get("activity")

    # 3. Demographic Extraction
    demographics: List[str] = []
    if any(k in query_lower for k in ["kid", "child", "children", "baby", "toddler", "infant"]):
        demographics.append("children")
    if any(k in query_lower for k in ["elderly", "senior", "grandparent", "old people", "aged"]):
        demographics.append("elderly")
    if any(k in query_lower for k in ["dog", "pet", "cat", "puppy"]):
        demographics.append("pets")

    if not demographics and current_extracted.get("demographics"):
        demographics = current_extracted.get("demographics", [])

    # 4. Timeframe Extraction
    timeframe = current_extracted.get("timeframe", "current")
    if "evening" in query_lower or "tonight" in query_lower:
        timeframe = "this evening"
    elif "tomorrow" in query_lower:
        timeframe = "tomorrow"
    elif "morning" in query_lower:
        timeframe = "morning"
    elif "afternoon" in query_lower:
        timeframe = "afternoon"
    elif "now" in query_lower or "today" in query_lower:
        timeframe = "current"

    # 5. Location Extraction
    extracted_location = None

    # Check common prepositions (handling punctuation like period, comma, question mark)
    loc_match = re.search(r"\b(?:in|at|for|around|near)\s+([A-Z][a-zA-Z\s]+?)(?:\s+(?:today|now|this|tomorrow|morning|evening|afternoon|\?|\.|$|,)|[\.,\?])", query)
    if loc_match:
        extracted_location = loc_match.group(1).strip()
    else:
        # Check known global/Indian cities
        known_cities = [
            "wellington", "bhopal", "mumbai", "delhi", "bengaluru", "bangalore", "chennai", "kolkata",
            "hyderabad", "pune", "ahmedabad", "jaipur", "lucknow", "chandigarh",
            "new york", "london", "tokyo", "paris", "berlin", "singapore", "sydney", "dubai"
        ]
        for city in known_cities:
            if re.search(rf"\b{city}\b", query_lower):
                extracted_location = city.title()
                break

    # Contextual Memory Carryover: If location not specified in follow-up turn, retain previous location!
    if not extracted_location:
        if current_extracted.get("location_name"):
            extracted_location = current_extracted.get("location_name")
        elif prev_location_info:
            extracted_location = prev_location_info.get("name")

    new_entities: ExtractedEntities = {
        "location_name": extracted_location,
        "activity": detected_activity,
        "demographics": demographics,
        "timeframe": timeframe,
        "is_adversarial": is_adversarial,
        "adversarial_reason": adversarial_reason,
        "confidence": 0.9 if extracted_location else 0.4
    }

    return {
        "extracted_entities": new_entities,
        "execution_trace": trace
    }


def fetch_weather_node(state: AgentState) -> Dict[str, Any]:
    """
    Node 2: Resolves location via geocoding and pulls live weather data from Open-Meteo.
    Stores JSON-serializable dictionaries in state.
    """
    trace = state.get("execution_trace", []) + ["fetch_weather_node"]
    entities = state.get("extracted_entities", {})
    location_name = entities.get("location_name")
    existing_loc = state.get("location_info")
    existing_weather = state.get("weather_data")

    if not location_name:
        return {
            "location_status": "unresolved",
            "weather_status": "skipped",
            "fallback_type": "LOCATION_NOT_FOUND",
            "fallback_message": "Could not determine which location to check weather for.",
            "execution_trace": trace
        }

    # If same location as previous turn and weather is already present, reuse
    if existing_loc and existing_weather and existing_loc.get("name", "").lower() == location_name.lower():
        logger.info(f"Reusing resolved weather for {existing_loc.get('name')} from session state.")
        return {
            "location_info": existing_loc,
            "location_status": "valid",
            "weather_data": existing_weather,
            "weather_status": "success",
            "fallback_type": "NONE",
            "execution_trace": trace
        }

    try:
        location_info = weather_client.geocode_city(location_name)
        weather_data = weather_client.fetch_weather(location_info.latitude, location_info.longitude, location=location_info)

        return {
            "location_info": location_info.model_dump(),
            "location_status": "valid",
            "weather_data": weather_data.model_dump(),
            "weather_status": "success",
            "fallback_type": "NONE",
            "execution_trace": trace
        }

    except LocationNotFoundError as e:
        logger.warning(f"Location not found: {e}")
        return {
            "location_info": None,
            "location_status": "unresolved",
            "weather_status": "skipped",
            "fallback_type": "LOCATION_NOT_FOUND",
            "fallback_message": str(e),
            "execution_trace": trace
        }
    except WeatherAPIUnavailableError as e:
        logger.error(f"Weather API error: {e}")
        return {
            "location_status": "api_error",
            "weather_status": "fetch_error",
            "fallback_type": "WEATHER_API_DOWN",
            "fallback_message": str(e),
            "execution_trace": trace
        }
    except Exception as e:
        logger.error(f"Unexpected error in fetch_weather_node: {e}")
        return {
            "location_status": "api_error",
            "weather_status": "fetch_error",
            "fallback_type": "WEATHER_API_DOWN",
            "fallback_message": f"Unexpected weather retrieval failure: {str(e)}",
            "execution_trace": trace
        }


def match_sop_node(state: AgentState) -> Dict[str, Any]:
    """
    Node 3: Evaluates active SOPs against weather telemetry and query context.
    Executes conflict resolution and severity ranking.
    """
    trace = state.get("execution_trace", []) + ["match_sop_node"]
    raw_weather = state.get("weather_data")
    entities = state.get("extracted_entities", {})

    if not raw_weather:
        return {
            "matched_sops": [],
            "primary_sop": None,
            "fallback_type": "WEATHER_API_DOWN",
            "execution_trace": trace
        }

    # Reconstitute WeatherData model
    weather = WeatherData(**raw_weather)
    activity = entities.get("activity", "")
    demographics = entities.get("demographics", [])

    matched = sop_engine.match_all_sops(weather=weather, activity=activity, demographics=demographics)

    if not matched:
        return {
            "matched_sops": [],
            "primary_sop": None,
            "fallback_type": "NO_SOP_GUIDANCE",
            "fallback_message": "No Standard Operating Procedure applies to this specific weather condition and activity combination.",
            "execution_trace": trace
        }

    primary = matched[0]
    is_synoptic = any(m.is_synoptic_override for m in matched)

    # Dump to dicts with json-compatible primitive types
    matched_dicts = [m.model_dump(mode="json") for m in matched]
    primary_dict = primary.model_dump(mode="json")

    return {
        "matched_sops": matched_dicts,
        "primary_sop": primary_dict,
        "is_synoptic_event_active": is_synoptic,
        "fallback_type": "NONE",
        "execution_trace": trace
    }


def generate_advisory_node(state: AgentState) -> Dict[str, Any]:
    """
    Node 4: Synthesizes final response strictly grounded in matched SOP(s) and exact Open-Meteo telemetry numbers.
    Enforces policy citations and prevents unapproved advice.
    """
    trace = state.get("execution_trace", []) + ["generate_advisory_node"]
    raw_weather = state.get("weather_data")
    raw_matched = state.get("matched_sops", [])
    raw_primary = state.get("primary_sop")
    user_query = state.get("user_query", "")

    if not raw_primary or not raw_weather:
        return {
            "final_response": "Unable to generate advisory without valid weather data and policy matches.",
            "execution_trace": trace
        }

    weather = WeatherData(**raw_weather)
    matched_sops = [SOPMatchResult(**m) for m in raw_matched]
    primary = SOPMatchResult(**raw_primary)

    citations = [f"{m.sop.id} ({m.sop.title} - Severity: {m.sop.severity.value})" for m in matched_sops]

    # Grounded metrics summary
    metrics = weather.summary_metrics()
    metrics_str = (
        f"Location: {weather.location.display_name()}\n"
        f"Temperature: {metrics['temperature_2m']}°C (Feels like: {metrics['apparent_temperature']}°C)\n"
        f"Precipitation: {metrics['precipitation']} mm\n"
        f"Precipitation Probability: {metrics['precipitation_probability']}%\n"
        f"Wind Speed: {metrics['wind_speed_10m']} km/h (Gusts: {metrics['wind_gusts_10m']} km/h)\n"
        f"UV Index: {metrics['uv_index']}\n"
        f"Conditions: {metrics['weather_description']} (WMO Code: {metrics['weather_code']})"
    )

    # Build prompt for LLM or deterministic fallback
    llm = get_llm(temperature=0.1)

    if llm is not None:
        try:
            matched_summary = "\n".join([
                f"- [{m.sop.id}] {m.sop.title} (Severity: {m.sop.severity.value}): {m.formatted_guidance} | Action: {m.sop.action_required}"
                for m in matched_sops
            ])

            system_prompt = (
                "You are MediBuddy's Weather-Advisory Support Bot. Your job is to answer outdoor activity safety "
                "questions strictly using live weather data and approved Standard Operating Procedures (SOPs).\n\n"
                "NON-NEGOTIABLE SAFETY RULES:\n"
                "1. Every piece of advice MUST strictly derive from the provided matched SOP(s). You are forbidden from inventing safety policies.\n"
                "2. Report weather numbers (temperature, wind speed, rain, UV) EXACTLY as provided in the Verified Live Weather Data. Never estimate or hallucinate numbers.\n"
                "3. If a regional emergency/synoptic rain system applies, lead immediately with that warning before activity-specific notes.\n"
                "4. Always explicitly cite the primary SOP ID and title at the conclusion of your advisory.\n"
                "5. Maintain a professional, clear, and empathetic tone."
            )

            user_prompt = (
                f"User Question: \"{user_query}\"\n\n"
                f"Verified Live Weather Data (Open-Meteo):\n{metrics_str}\n\n"
                f"Matched SOP Policies:\n{matched_summary}\n\n"
                f"Compose the safety advisory for the user grounded strictly in these facts and rules."
            )

            ai_response = llm.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt)
            ])
            response_text = ai_response.content if hasattr(ai_response, "content") else str(ai_response)
        except Exception as e:
            logger.warning(f"LLM synthesis failed ({e}). Using deterministic template generator.")
            response_text = _synthesize_deterministic(weather, matched_sops, primary)
    else:
        response_text = _synthesize_deterministic(weather, matched_sops, primary)

    # Append citation badge if not already present
    citation_badge = f"\n\n---\n**Policy Citation:** `[{primary.sop.id}]` {primary.sop.title} (`Severity: {primary.sop.severity.value}`)"
    if primary.sop.id not in response_text:
        response_text += citation_badge

    return {
        "final_response": response_text,
        "citations": citations,
        "execution_trace": trace
    }


def _synthesize_deterministic(weather: WeatherData, matched_sops: List[SOPMatchResult], primary: SOPMatchResult) -> str:
    """Deterministic, high-reliability fallback response synthesizer."""
    m = weather.summary_metrics()
    primary_guidance = primary.formatted_guidance or primary.sop.guidance
    
    parts = []
    # Location & live weather header
    parts.append(f"**Weather Advisory for {weather.location.display_name()}**")
    parts.append(
        f"*Live Conditions:* **{m['temperature_2m']}°C** (Feels like {m['apparent_temperature']}°C), "
        f"Wind: **{m['wind_speed_10m']} km/h**, Rain: **{m['precipitation']} mm** ({m['precipitation_probability']}% prob), "
        f"UV Index: **{m['uv_index']}**, Weather: **{m['weather_description']}**.\n"
    )

    # Primary guidance
    parts.append(f"### Safety Guidance ({primary.sop.severity.value} Severity)")
    parts.append(primary_guidance)
    parts.append(f"\n**Required Action:** {primary.sop.action_required}")

    # Secondary matched policies if any
    if len(matched_sops) > 1:
        parts.append("\n**Additional Relevant Policy Notices:**")
        for extra in matched_sops[1:]:
            parts.append(f"- **[{extra.sop.id}] {extra.sop.title}** ({extra.sop.severity.value}): {extra.formatted_guidance}")

    return "\n".join(parts)


# ------------------------------------------------------------------------------
# Fallback Node Implementations
# ------------------------------------------------------------------------------

def location_fallback_node(state: AgentState) -> Dict[str, Any]:
    """Node for handling unresolvable or missing locations."""
    trace = state.get("execution_trace", []) + ["location_fallback_node"]
    entities = state.get("extracted_entities", {})
    loc_name = entities.get("location_name")

    if loc_name:
        msg = (
            f"I could not resolve the geographic location for **'{loc_name}'** via Open-Meteo geocoding. "
            f"Please specify a valid city or town name so I can fetch live weather data and evaluate safety policies."
        )
    else:
        msg = (
            "Please specify a city or region (for example: *'Is it safe to cycle in Bhopal today?'*) "
            "so I can check the live weather conditions against our Standard Operating Procedures."
        )

    return {
        "final_response": msg,
        "citations": [],
        "fallback_type": "LOCATION_NOT_FOUND",
        "execution_trace": trace
    }


def weather_error_fallback_node(state: AgentState) -> Dict[str, Any]:
    """Node for handling Open-Meteo API down or network failures honestly."""
    trace = state.get("execution_trace", []) + ["weather_error_fallback_node"]
    fb_msg = state.get("fallback_message", "Weather API unreachable")

    msg = (
        "⚠️ **Live Weather Service Unavailable**\n\n"
        "We are currently unable to retrieve verified live weather telemetry from Open-Meteo. "
        "Under our safety protocol, I cannot guess or assume weather conditions without verified data. "
        f"\n\n*Diagnostic details:* {fb_msg}. Please try again in a few moments."
    )

    return {
        "final_response": msg,
        "citations": [],
        "fallback_type": "WEATHER_API_DOWN",
        "execution_trace": trace
    }


def no_guidance_fallback_node(state: AgentState) -> Dict[str, Any]:
    """Node for handling queries where no SOP applies."""
    trace = state.get("execution_trace", []) + ["no_guidance_fallback_node"]
    raw_weather = state.get("weather_data")

    weather_summary = ""
    if raw_weather:
        weather = WeatherData(**raw_weather)
        m = weather.summary_metrics()
        weather_summary = (
            f"\n\n*Current conditions in {weather.location.display_name()}:* "
            f"Temperature {m['temperature_2m']}°C, Wind {m['wind_speed_10m']} km/h, Rain {m['precipitation']} mm, UV {m['uv_index']}."
        )

    msg = (
        "ℹ️ **No Specific Safety Policy Guidance Available**\n\n"
        "We do not have a Standard Operating Procedure (SOP) that covers this specific activity and condition combination. "
        "To ensure your safety and compliance, we do not invent unapproved safety advice."
        f"{weather_summary}\n\n"
        "Please exercise standard personal judgment or check official local advisories."
    )

    return {
        "final_response": msg,
        "citations": ["NO_MATCHING_SOP"],
        "fallback_type": "NO_SOP_GUIDANCE",
        "execution_trace": trace
    }


def adversarial_fallback_node(state: AgentState) -> Dict[str, Any]:
    """Node for rebuffing prompt injection attempts."""
    trace = state.get("execution_trace", []) + ["adversarial_fallback_node"]
    
    msg = (
        "🛡️ **Safety Protocol Alert**\n\n"
        "I cannot override, ignore, or fabricate safety policies. All outdoor activity recommendations "
        "must be strictly grounded in verified Open-Meteo weather data and official Standard Operating Procedures (SOPs). "
        "\n\nPlease provide a standard outdoor activity question (e.g. *'Is it safe to cycle in Bhopal today?'*) for safety evaluation."
    )

    return {
        "final_response": msg,
        "citations": ["ADVERSARIAL_PREVENTION_TRIGGERED"],
        "fallback_type": "ADVERSARIAL_INJECTION",
        "execution_trace": trace
    }
