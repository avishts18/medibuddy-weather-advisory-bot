"""
Open-Meteo Live Weather & Geocoding Client
"""
import logging
from typing import Optional, Tuple, Dict, Any
import httpx

from src.config import (
    OPEN_METEO_GEOCODING_URL,
    OPEN_METEO_FORECAST_URL,
    OPEN_METEO_TIMEOUT
)
from src.models.weather import LocationInfo, WeatherData

logger = logging.getLogger("weather_bot.weather_client")


class WeatherClientError(Exception):
    """Custom exception for weather client failures."""
    pass


class LocationNotFoundError(WeatherClientError):
    """Raised when a city/location name cannot be geocoded."""
    pass


class WeatherAPIUnavailableError(WeatherClientError):
    """Raised when the Open-Meteo API is unreachable or returns a server error."""
    pass


class WeatherClient:
    """
    Robust HTTP client for Open-Meteo Geocoding and Forecast API.
    Enforces explicit parameters, timeout boundaries, and truthful failure reporting.
    """

    def __init__(self, timeout: int = OPEN_METEO_TIMEOUT):
        self.timeout = timeout

    def geocode_city(self, city_name: str) -> LocationInfo:
        """
        Resolves a city/locality name to geographic coordinates using Open-Meteo Geocoding.
        Takes the top candidate from the search result.
        """
        if not city_name or not city_name.strip():
            raise LocationNotFoundError("Empty location name provided.")

        clean_name = city_name.strip()
        params = {
            "name": clean_name,
            "count": 5,
            "language": "en",
            "format": "json"
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(OPEN_METEO_GEOCODING_URL, params=params)

            if response.status_code != 200:
                logger.error(f"Geocoding API responded with HTTP {response.status_code}: {response.text}")
                raise WeatherAPIUnavailableError(f"Geocoding service returned HTTP {response.status_code}.")

            data = response.json()
            results = data.get("results")

            if not results or len(results) == 0:
                logger.info(f"No geocoding match found for query: '{clean_name}'")
                raise LocationNotFoundError(f"Could not resolve geographic location for '{clean_name}'.")

            # Extract primary candidate
            top = results[0]
            location = LocationInfo(
                name=top.get("name", clean_name),
                latitude=float(top.get("latitude")),
                longitude=float(top.get("longitude")),
                country=top.get("country"),
                admin1=top.get("admin1"),
                timezone=top.get("timezone", "auto"),
                elevation=top.get("elevation")
            )
            logger.info(f"Resolved '{clean_name}' to {location.display_name()} ({location.latitude}, {location.longitude})")
            return location

        except httpx.TimeoutException:
            logger.error(f"Geocoding timeout for '{clean_name}'")
            raise WeatherAPIUnavailableError("Geocoding service timed out.")
        except httpx.RequestError as e:
            logger.error(f"Network error during geocoding for '{clean_name}': {e}")
            raise WeatherAPIUnavailableError(f"Geocoding network error: {str(e)}")

    def fetch_weather(
        self,
        latitude: float,
        longitude: float,
        location: Optional[LocationInfo] = None,
        simulate_failure: bool = False
    ) -> WeatherData:
        """
        Pulls live weather metrics from Open-Meteo Forecast endpoint.
        Explicitly requests current and hourly values: temperature, apparent temperature,
        relative humidity, precipitation, precipitation probability, wind speed, wind gusts,
        and UV index.
        """
        if simulate_failure:
            logger.warning("Simulated Weather API Failure triggered.")
            raise WeatherAPIUnavailableError("Open-Meteo forecast service is temporarily unreachable (Simulated Failure).")

        loc = location or LocationInfo(
            name=f"Lat {latitude:.2f}, Lon {longitude:.2f}",
            latitude=latitude,
            longitude=longitude
        )

        current_params = [
            "temperature_2m",
            "relative_humidity_2m",
            "apparent_temperature",
            "precipitation",
            "precipitation_probability",
            "weather_code",
            "wind_speed_10m",
            "wind_gusts_10m",
            "uv_index",
            "is_day"
        ]

        hourly_params = [
            "temperature_2m",
            "precipitation",
            "precipitation_probability",
            "wind_speed_10m",
            "uv_index"
        ]

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": ",".join(current_params),
            "hourly": ",".join(hourly_params),
            "timezone": loc.timezone or "auto",
            "forecast_days": 2
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(OPEN_METEO_FORECAST_URL, params=params)

            if response.status_code != 200:
                logger.error(f"Weather Forecast API responded with HTTP {response.status_code}: {response.text}")
                raise WeatherAPIUnavailableError(f"Forecast service returned HTTP {response.status_code}.")

            data = response.json()
            if "current" not in data:
                logger.error("No 'current' object in Open-Meteo payload.")
                raise WeatherAPIUnavailableError("Open-Meteo returned incomplete payload missing current weather readings.")

            weather_data = WeatherData.from_open_meteo(location=loc, data=data)
            logger.info(
                f"Fetched weather for {loc.name}: Temp={weather_data.temperature_2m}°C, "
                f"Rain={weather_data.precipitation}mm, RainProb={weather_data.precipitation_probability}%, "
                f"Wind={weather_data.wind_speed_10m}km/h, UV={weather_data.uv_index}"
            )
            return weather_data

        except httpx.TimeoutException:
            logger.error(f"Weather Forecast timeout for coordinates ({latitude}, {longitude})")
            raise WeatherAPIUnavailableError("Weather forecast service timed out.")
        except httpx.RequestError as e:
            logger.error(f"Network error during weather forecast call: {e}")
            raise WeatherAPIUnavailableError(f"Weather service network error: {str(e)}")

    def get_weather_for_location(
        self,
        city_name: str,
        simulate_failure: bool = False
    ) -> Tuple[LocationInfo, WeatherData]:
        """Convenience helper to resolve city and pull weather in one step."""
        if simulate_failure:
            raise WeatherAPIUnavailableError("Weather API simulated outage.")
        location = self.geocode_city(city_name)
        weather = self.fetch_weather(location.latitude, location.longitude, location=location)
        return location, weather
