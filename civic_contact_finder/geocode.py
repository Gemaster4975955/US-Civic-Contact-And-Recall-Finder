import math
import re
import logging
import os
import threading
import time
from collections import OrderedDict
from typing import Tuple, Union

import requests
from flask import request

Number = Union[float, int]
logger = logging.getLogger(__name__)
_CACHE_TTL_SECONDS = 24 * 60 * 60
_geocode_cache = OrderedDict()
_geocode_lock = threading.Lock()
_last_request_at = 0.0
_MAX_CACHE_ENTRIES = 2048


class GeocodingError(Exception):
    """Raised when the geocoding provider cannot be reached or parsed."""


def looks_like_location(text: str | None) -> bool:
    value = (text or '').strip()
    if not value:
        return False

    street_suffixes = (
        'street|st|avenue|ave|road|rd|boulevard|blvd|lane|ln|drive|dr|court|ct|'
        'circle|cir|parkway|pkwy|way|trail|ter|terrace'
    )
    if re.search(rf'\b(?:{street_suffixes})\b', value, re.IGNORECASE):
        return True
    if re.search(r'\b(?:near|by|at|in|around|on|outside|inside)\b', value, re.IGNORECASE):
        return True
    return any(ch.isdigit() for ch in value)


# ---------------------------------------------------------
# Get user coordinates
# ---------------------------------------------------------
def get_user_coordinates() -> Tuple[float | None, float | None]:
    lat = request.args.get("lat")
    lon = request.args.get("lon")

    return validate_coordinates(lat, lon)


# ---------------------------------------------------------
# Convert a location string into latitude/longitude
# ---------------------------------------------------------
def geocode_location_details(
    location: str,
) -> Tuple[float | None, float | None, str | None]:
    global _last_request_at

    normalized_location = ' '.join(location.strip().split())
    cache_key = normalized_location.casefold()
    now = time.monotonic()

    with _geocode_lock:
        cached = _geocode_cache.get(cache_key)
        if cached and now - cached[0] < _CACHE_TTL_SECONDS:
            _geocode_cache.move_to_end(cache_key)
            return cached[1]

        wait_seconds = 1.0 - (now - _last_request_at)
        if wait_seconds > 0:
            time.sleep(wait_seconds)

        contact = os.environ.get('GEOCODER_CONTACT', '').strip()
        user_agent = 'CivicContactFinder/1.0'
        if contact:
            user_agent += f' ({contact})'

        url = "https://nominatim.openstreetmap.org/search"
        params = {
            "q": normalized_location,
            "format": "json",
            "limit": 1,
            "countrycodes": "us,pr,gu,vi,as,mp",
            "addressdetails": 1,
        }

        try:
            response = requests.get(
                url,
                params=params,
                headers={"User-Agent": user_agent},
                timeout=6,
            )
            _last_request_at = time.monotonic()
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Geocoding provider request failed: %s", type(exc).__name__)
            raise GeocodingError("The location service is temporarily unavailable.") from exc

        try:
            if not data:
                result = (None, None, None)
            else:
                if not isinstance(data, list) or not isinstance(data[0], dict):
                    raise ValueError("Geocoder returned an invalid result.")
                address = data[0].get("address", {})
                if not isinstance(address, dict):
                    raise ValueError("Geocoder returned an invalid address.")
                state = address.get("state") or address.get("territory")
                if not isinstance(state, str):
                    state = None
                latitude, longitude = validate_coordinates(
                    data[0].get("lat"),
                    data[0].get("lon"),
                )
                if latitude is None or longitude is None:
                    raise ValueError("Geocoder returned invalid coordinates.")
                result = (latitude, longitude, state)
        except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
            logger.warning("Geocoding provider returned an invalid response.")
            raise GeocodingError("The location service returned an invalid response.") from exc

        _geocode_cache[cache_key] = (time.monotonic(), result)
        _geocode_cache.move_to_end(cache_key)
        while len(_geocode_cache) > _MAX_CACHE_ENTRIES:
            _geocode_cache.popitem(last=False)
        return result


def geocode_location(location: str) -> Tuple[float | None, float | None]:
    lat, lon, _ = geocode_location_details(location)
    return lat, lon


# ---------------------------------------------------------
# Validate lat/lon values
# ---------------------------------------------------------
def validate_coordinates(
    lat: Number | str | None,
    lon: Number | str | None
) -> Tuple[float | None, float | None]:
    if lat is None or lon is None:
        return None, None

    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (ValueError, TypeError):
        return None, None

    if not (-90 <= lat_f <= 90 and -180 <= lon_f <= 180):
        return None, None

    return lat_f, lon_f


def haversine_km(lat1: Number, lon1: Number, lat2: Number, lon2: Number) -> float:
    earth_radius_km = 6371.0
    lat1_r, lon1_r, lat2_r, lon2_r = map(
        math.radians,
        (float(lat1), float(lon1), float(lat2), float(lon2)),
    )
    delta_lat = lat2_r - lat1_r
    delta_lon = lon2_r - lon1_r
    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(delta_lon / 2) ** 2
    )
    return earth_radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ---------------------------------------------------------
# Compute a bounding box around a point (radius in km)
# ---------------------------------------------------------
def get_bounding_box(
    lat: Number,
    lon: Number,
    radius_km: Number
):
    lat_f = float(lat)
    lon_f = float(lon)
    radius_f = float(radius_km)

    earth_radius = 6371.0

    lat_delta = (radius_f / earth_radius) * (180 / math.pi)
    north = lat_f + lat_delta
    south = lat_f - lat_delta

    lon_delta = (radius_f / (earth_radius * math.cos(math.radians(lat_f)))) * (180 / math.pi)
    east = lon_f + lon_delta
    west = lon_f - lon_delta

    return {
        "north": north,
        "south": south,
        "east": east,
        "west": west
    }