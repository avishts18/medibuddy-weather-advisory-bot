"""
SOP (Standard Operating Procedure) Policy Models
"""
from enum import Enum
from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field


class SeverityLevel(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MODERATE = "MODERATE"
    LOW_ADVISORY = "LOW_ADVISORY"

    @property
    def rank(self) -> int:
        mapping = {
            SeverityLevel.CRITICAL: 4,
            SeverityLevel.HIGH: 3,
            SeverityLevel.MODERATE: 2,
            SeverityLevel.LOW_ADVISORY: 1,
        }
        return mapping.get(self, 0)


class ConditionRule(BaseModel):
    """A single metric comparison rule (e.g. wind_speed_10m >= 40)."""
    metric: str
    operator: str # '>=', '<=', '>', '<', '==', '!=', 'in'
    value: Union[float, int, List[Union[int, float]]]
    unit: Optional[str] = None


class FuzzyEvaluationConfig(BaseModel):
    ideal_ranges: Optional[Dict[str, List[float]]] = None
    unfavorable_triggers: Optional[List[str]] = None
    context_keywords: Optional[List[str]] = None


class SOPConditions(BaseModel):
    type: str = "compound_or" # 'compound_or', 'compound_and', 'fuzzy_composite', 'single'
    rules: Optional[List[ConditionRule]] = Field(default_factory=list)
    fuzzy_match: Optional[Dict[str, Any]] = None
    fuzzy_evaluation: Optional[FuzzyEvaluationConfig] = None


class SOPRule(BaseModel):
    """
    Standard Operating Procedure (SOP) Rule representation.
    Loaded dynamically from external policy storage (data/sops.yaml).
    """
    id: str
    title: str
    category: str
    severity: SeverityLevel
    priority: int = 50 # Base priority for tie-breaking
    description: str
    conditions: SOPConditions
    applies_to_activities: List[str] = Field(default_factory=lambda: ["*"])
    target_demographics: Optional[List[str]] = None
    action_required: str
    guidance: str

    def applies_to_activity(self, activity: str) -> bool:
        """Check if rule applies to a given activity keyword or wildcard."""
        if "*" in self.applies_to_activities:
            return True
        if not activity:
            return False
        activity_lower = activity.lower().strip()
        return any(act.lower() in activity_lower or activity_lower in act.lower() for act in self.applies_to_activities)

    def applies_to_demographic(self, text: str) -> bool:
        """Check demographic targeting (children, elderly, pets)."""
        if not self.target_demographics:
            return True # No demographic restriction
        text_lower = text.lower()
        return any(demo.lower() in text_lower for demo in self.target_demographics)


class SOPMatchResult(BaseModel):
    """Detailed matching result for an evaluated SOP."""
    sop: SOPRule
    is_match: bool
    match_score: float = 1.0 # 0.0 to 1.0
    satisfied_conditions: List[str] = Field(default_factory=list)
    triggered_reasons: List[str] = Field(default_factory=list)
    formatted_guidance: str = ""
    is_synoptic_override: bool = False
