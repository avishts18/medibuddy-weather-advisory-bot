"""
Weather data models for Open-Meteo Integration
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


# Standard WMO Weather Code Descriptions
WMO_WEATHER_CODES: Dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow fall",
    73: "Moderate snow fall",
    75: "Heavy snow fall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm (slight or moderate)",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


class LocationInfo(BaseModel):
    """Geocoded location information from Open-Meteo."""
    name: str
    latitude: float
    longitude: float
    country: Optional[str] = None
    admin1: Optional[str] = None # State/Province
    timezone: Optional[str] = "auto"
    elevation: Optional[float] = None

    def display_name(self) -> str:
        parts = [self.name]
        if self.admin1:
            parts.append(self.admin1)
        if self.country:
            parts.append(self.country)
        return ", ".join(parts)


class HourlyForecast(BaseModel):
    """Hourly forecast series for timeframe queries (e.g. 'this evening', 'tomorrow morning')."""
    times: List[str] = Field(default_factory=list)
    temperatures: List[float] = Field(default_factory=list)
    precipitations: List[float] = Field(default_factory=list)
    precipitation_probabilities: List[int] = Field(default_factory=list)
    wind_speeds: List[float] = Field(default_factory=list)
    uv_indices: List[float] = Field(default_factory=list)


class WeatherData(BaseModel):
    """
    Verified weather telemetry extracted directly from Open-Meteo API.
    The numbers here are strictly passed to the reasoning engine and prompt.
    """
    location: LocationInfo
    time: str
    temperature_2m: float
    apparent_temperature: float
    relative_humidity_2m: float
    precipitation: float
    precipitation_probability: int
    weather_code: int
    wind_speed_10m: float
    wind_gusts_10m: float
    uv_index: float
    is_day: int = 1
    weather_description: str = "Unknown"
    hourly: Optional[HourlyForecast] = None
    raw_response: Optional[Dict[str, Any]] = None

    @classmethod
    def from_open_meteo(cls, location: LocationInfo, data: Dict[str, Any]) -> "WeatherData":
        current = data.get("current", {})
        code = int(current.get("weather_code", 0))
        desc = WMO_WEATHER_CODES.get(code, f"Weather code {code}")

        hourly_obj = None
        if "hourly" in data:
            h = data["hourly"]
            hourly_obj = HourlyForecast(
                times=h.get("time", [])[:24],
                temperatures=[float(x) for x in h.get("temperature_2m", [])[:24]],
                precipitations=[float(x) for x in h.get("precipitation", [])[:24]],
                precipitation_probabilities=[int(x) if x is not None else 0 for x in h.get("precipitation_probability", [])[:24]],
                wind_speeds=[float(x) for x in h.get("wind_speed_10m", [])[:24]],
                uv_indices=[float(x) if x is not None else 0.0 for x in h.get("uv_index", [])[:24]],
            )

        return cls(
            location=location,
            time=str(current.get("time", "")),
            temperature_2m=float(current.get("temperature_2m", 0.0)),
            apparent_temperature=float(current.get("apparent_temperature", current.get("temperature_2m", 0.0))),
            relative_humidity_2m=float(current.get("relative_humidity_2m", 0.0)),
            precipitation=float(current.get("precipitation", 0.0)),
            precipitation_probability=int(current.get("precipitation_probability", 0) or 0),
            weather_code=code,
            wind_speed_10m=float(current.get("wind_speed_10m", 0.0)),
            wind_gusts_10m=float(current.get("wind_gusts_10m", current.get("wind_speed_10m", 0.0))),
            uv_index=float(current.get("uv_index", 0.0) or 0.0),
            is_day=int(current.get("is_day", 1)),
            weather_description=desc,
            hourly=hourly_obj,
            raw_response=data
        )

    def summary_metrics(self) -> Dict[str, Any]:
        """Returns clean metric dictionary for condition evaluation and prompt synthesis."""
        return {
            "temperature_2m": self.temperature_2m,
            "apparent_temperature": self.apparent_temperature,
            "relative_humidity_2m": self.relative_humidity_2m,
            "precipitation": self.precipitation,
            "precipitation_probability": self.precipitation_probability,
            "weather_code": self.weather_code,
            "weather_description": self.weather_description,
            "wind_speed_10m": self.wind_speed_10m,
            "wind_gusts_10m": self.wind_gusts_10m,
            "uv_index": self.uv_index,
        }
