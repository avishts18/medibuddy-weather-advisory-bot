"""
Dynamic SOP (Standard Operating Procedures) Engine
Handles hot-reloading from YAML/JSON, condition matching, fuzzy composite evaluation,
and multi-policy conflict resolution & severity ranking.
"""
import os
import logging
from typing import List, Dict, Any, Optional, Tuple
import yaml

from src.config import DEFAULT_SOP_PATH
from src.models.sop import SOPRule, SOPMatchResult, ConditionRule, SeverityLevel
from src.models.weather import WeatherData

logger = logging.getLogger("weather_bot.sop_engine")


class SOPEngine:
    """
    SOP policy manager and evaluator.
    Designed for zero-code policy additions: changing sops.yaml immediately
    updates behavior on the very next query without application restarts.
    """

    def __init__(self, sops_path: Optional[str] = None):
        self.sops_path = sops_path or DEFAULT_SOP_PATH
        self._sops: List[SOPRule] = []
        self._last_loaded_mtime: float = 0
        self.load_sops()

    def load_sops(self, force_reload: bool = False) -> List[SOPRule]:
        """Loads or reloads SOPs from the external YAML file if modified."""
        if not os.path.exists(self.sops_path):
            logger.error(f"SOP configuration file not found at: {self.sops_path}")
            return []

        mtime = os.path.getmtime(self.sops_path)
        if not force_reload and self._sops and mtime == self._last_loaded_mtime:
            return self._sops

        try:
            with open(self.sops_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            raw_sops = data.get("sops", [])
            parsed_sops: List[SOPRule] = []
            for item in raw_sops:
                try:
                    rule = SOPRule(**item)
                    parsed_sops.append(rule)
                except Exception as ex:
                    logger.error(f"Error parsing SOP entry {item.get('id', 'unknown')}: {ex}")

            self._sops = parsed_sops
            self._last_loaded_mtime = mtime
            logger.info(f"Successfully loaded {len(self._sops)} SOP policies from {self.sops_path}")
            return self._sops
        except Exception as e:
            logger.error(f"Failed to read SOP YAML file: {e}")
            return self._sops

    def get_all_sops(self) -> List[SOPRule]:
        """Returns all currently active SOPs (hot-reloaded if file changed)."""
        return self.load_sops()

    def evaluate_condition_rule(self, rule: ConditionRule, metrics: Dict[str, Any]) -> Tuple[bool, str]:
        """Evaluates a single metric rule against live weather metrics."""
        metric_name = rule.metric
        if metric_name not in metrics:
            return False, f"Metric '{metric_name}' not present in weather data"

        actual_val = metrics[metric_name]
        target_val = rule.value
        op = rule.operator

        matched = False
        if op == ">=":
            matched = actual_val >= target_val
        elif op == "<=":
            matched = actual_val <= target_val
        elif op == ">":
            matched = actual_val > target_val
        elif op == "<":
            matched = actual_val < target_val
        elif op == "==":
            matched = actual_val == target_val
        elif op == "!=":
            matched = actual_val != target_val
        elif op == "in":
            if isinstance(target_val, list):
                matched = actual_val in target_val
            else:
                matched = str(actual_val) in str(target_val)

        unit_str = f" {rule.unit}" if rule.unit else ""
        explanation = f"{metric_name} ({actual_val}{unit_str}) {op} {target_val}{unit_str}"
        return matched, explanation

    def evaluate_fuzzy_picnic(self, weather: WeatherData, activity: str) -> SOPMatchResult:
        """
        Specialized fuzzy composite evaluator for leisure / picnic scenarios.
        Evaluates comfort parameters across temperature, wind, precipitation, and UV.
        """
        metrics = weather.summary_metrics()
        temp = metrics["temperature_2m"]
        wind = metrics["wind_speed_10m"]
        precip = metrics["precipitation"]
        precip_prob = metrics["precipitation_probability"]

        # Find picnic SOP
        sop = next((s for s in self._sops if s.id == "SOP-REC-001"), None)
        if not sop:
            return SOPMatchResult(
                sop=SOPRule(
                    id="SOP-REC-001",
                    title="Picnic Assessment",
                    category="leisure",
                    severity=SeverityLevel.LOW_ADVISORY,
                    description="",
                    conditions={"type": "fuzzy_composite"},
                    action_required="",
                    guidance=""
                ),
                is_match=False
            )

        unfavorable_factors = []
        if precip > 0.5 or precip_prob >= 40:
            unfavorable_factors.append(f"Rain threat is active ({precip} mm, {precip_prob}% probability) risking wet grass and spoiled picnic blankets")
        if wind > 25.0:
            unfavorable_factors.append(f"Wind gusts of {wind} km/h make outdoor dining and picnic setups difficult")
        if temp > 33.0:
            unfavorable_factors.append(f"High thermal index ({temp}°C) creates heat discomfort and rapid food spoilage")
        elif temp < 14.0:
            unfavorable_factors.append(f"Chilly temperature ({temp}°C) may be uncomfortable for sitting outdoors")

        is_match = True # Picnic rule always applies when picnic is queried
        if not unfavorable_factors:
            rating = "Ideal / Excellent"
            custom_guidance = (
                f"Picnic & Outdoor Leisure Suitability: **{rating}**. Current conditions in {weather.location.name} "
                f"are pleasant ({temp}°C, gentle breeze {wind} km/h, {precip_prob}% rain probability). "
                f"Lawn ground conditions and ambient comfort are favorable for outdoor dining."
            )
        else:
            rating = "Suboptimal / Precaution Recommended"
            factors_str = "; ".join(unfavorable_factors)
            custom_guidance = (
                f"Picnic & Outdoor Leisure Suitability: **{rating}**. "
                f"While you may venture out, note these concerns: {factors_str}."
            )

        return SOPMatchResult(
            sop=sop,
            is_match=is_match,
            match_score=0.9,
            satisfied_conditions=[f"Composite picnic evaluation: Rating={rating}"],
            triggered_reasons=unfavorable_factors or ["Optimal mild weather conditions across all comfort metrics"],
            formatted_guidance=custom_guidance
        )

    def evaluate_sop(
        self,
        sop: SOPRule,
        weather: WeatherData,
        activity: str = "",
        demographics: Optional[List[str]] = None
    ) -> Optional[SOPMatchResult]:
        """Evaluates a single SOP against current weather telemetry and context."""
        # 1. Activity filter check
        if not sop.applies_to_activity(activity):
            return None

        # 2. Demographic filter check (if rule targets specific groups)
        if sop.target_demographics and demographics:
            has_demo_match = any(d.lower() in [td.lower() for td in sop.target_demographics] for d in demographics)
            if not has_demo_match and "*" not in sop.applies_to_activities:
                return None

        metrics = weather.summary_metrics()
        cond_type = sop.conditions.type

        # Handle fuzzy composite picnic SOP
        if cond_type == "fuzzy_composite" or sop.id == "SOP-REC-001":
            return self.evaluate_fuzzy_picnic(weather, activity)

        rules = sop.conditions.rules or []
        if not rules:
            return None

        evaluated_rules = [self.evaluate_condition_rule(r, metrics) for r in rules]
        results = [r[0] for r in evaluated_rules]
        explanations = [r[1] for r in evaluated_rules if r[0]]

        is_match = False
        if cond_type == "compound_or":
            is_match = any(results)
        elif cond_type == "compound_and":
            is_match = all(results) and len(results) > 0
        else:
            is_match = any(results)

        if not is_match:
            return None

        # Format guidance with live weather metrics
        formatted_guidance = sop.guidance
        try:
            formatted_guidance = sop.guidance.format(**metrics)
        except Exception:
            # Fallback if unformatted token exists
            pass

        is_synoptic = sop.category == "regional_emergency"

        return SOPMatchResult(
            sop=sop,
            is_match=True,
            match_score=1.0,
            satisfied_conditions=explanations,
            triggered_reasons=explanations,
            formatted_guidance=formatted_guidance,
            is_synoptic_override=is_synoptic
        )

    def match_all_sops(
        self,
        weather: WeatherData,
        activity: str = "",
        demographics: Optional[List[str]] = None
    ) -> List[SOPMatchResult]:
        """
        Evaluates all active SOPs and returns matched results.
        Enforces Conflict Resolution:
        1. Regional Synoptic Emergencies (Priority 100/95) override and lead.
        2. Highest Severity rank (CRITICAL > HIGH > MODERATE > LOW_ADVISORY).
        3. SOP Priority score tie-breaker.
        """
        sops = self.get_all_sops()
        matched: List[SOPMatchResult] = []

        for sop in sops:
            match_res = self.evaluate_sop(sop, weather, activity, demographics)
            if match_res and match_res.is_match:
                matched.append(match_res)

        # Sort matches by Conflict Resolution Hierarchy:
        # 1. Synoptic override flag (True first)
        # 2. Severity rank (4, 3, 2, 1)
        # 3. Policy priority score (descending)
        matched.sort(
            key=lambda x: (
                1 if x.is_synoptic_override else 0,
                x.sop.severity.rank,
                x.sop.priority
            ),
            reverse=True
        )

        logger.info(f"Matched {len(matched)} SOPs for activity '{activity}' in {weather.location.name}")
        return matched
