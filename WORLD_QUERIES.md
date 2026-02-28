# World Queries — `agent/world/`

## Overview

External data tools that give Clyde live awareness beyond the cabin.
All external APIs are wrapped in typed tools — Claude never constructs
raw HTTP requests. A shared cache layer prevents redundant API calls
within a ride session.

---

## Dependencies

```bash
pip install httpx python-dotenv
```

Add to `requirements.txt`:
```
httpx>=0.27.0
```

---

## Environment Variables

```env
OPENWEATHER_API_KEY=
AERODATABOX_API_KEY=
SPORTSDATA_NFL_KEY=
SPORTSDATA_NBA_KEY=
SPORTSDATA_MLB_KEY=
NEWSAPI_KEY=
GOOGLE_PLACES_API_KEY=
LOCAL_CITY=Atlanta
LOCAL_TIMEZONE=America/New_York
LOCAL_SPORTS_TEAMS=Falcons,Braves,Hawks,Atlanta United
```

---

## Project Structure

```
agent/world/
├── __init__.py
├── cache.py          # shared TTL cache
├── weather.py
├── flights.py
├── sports.py
├── news.py
└── places.py
```

---

## `agent/world/cache.py`

```python
# agent/world/cache.py

import time
from typing import Any, Callable

# TTL in seconds per data type
CACHE_TTL: dict[str, int] = {
    "weather":  600,    # 10 min
    "flight":   120,    # 2 min — status changes near departure
    "sports":   300,    # 5 min
    "news":     900,    # 15 min
    "places":   3600,   # 1 hour — POI data is stable
}

_store: dict[str, tuple[Any, float]] = {}


def get(key: str, ttl_key: str) -> Any | None:
    if key not in _store:
        return None
    value, ts = _store[key]
    if time.monotonic() - ts > CACHE_TTL[ttl_key]:
        del _store[key]
        return None
    return value


def set(key: str, ttl_key: str, value: Any) -> None:
    _store[key] = (value, time.monotonic())


def clear() -> None:
    """Call at the start of each new ride session."""
    _store.clear()


def cached(key: str, ttl_key: str, fetch_fn: Callable) -> Any:
    """Fetch from cache or call fetch_fn and store result."""
    value = get(key, ttl_key)
    if value is not None:
        return value
    value = fetch_fn()
    set(key, ttl_key, value)
    return value
```

---

## `agent/world/weather.py`

```python
# agent/world/weather.py
# OpenWeatherMap — free tier sufficient

import os
import httpx
from agent.world import cache

API_KEY = os.getenv("OPENWEATHER_API_KEY")
BASE = "https://api.openweathermap.org/data/2.5"


async def get_weather(location: str) -> dict:
    """
    Returns current weather for a location string.
    Location can be a city name, neighborhood, or stop name.
    """
    cache_key = f"weather:{location.lower()}"
    cached = cache.get(cache_key, "weather")
    if cached:
        return cached

    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{BASE}/weather", params={
            "q": location,
            "appid": API_KEY,
            "units": "imperial",
        }, timeout=5.0)
        resp.raise_for_status()
        data = resp.json()

    result = {
        "location": data["name"],
        "temp_f": round(data["main"]["temp"]),
        "feels_like_f": round(data["main"]["feels_like"]),
        "condition": data["weather"][0]["description"],
        "humidity": data["main"]["humidity"],
        "wind_mph": round(data["wind"]["speed"]),
        "rain_1h_mm": data.get("rain", {}).get("1h", 0),
    }

    cache.set(cache_key, "weather", result)
    return result


def format_weather(w: dict) -> str:
    """Format weather result into a natural spoken sentence."""
    rain = " Rain expected." if w["rain_1h_mm"] > 0.5 else ""
    return (
        f"It's {w['temp_f']}° and {w['condition']} at {w['location']}."
        f" Feels like {w['feels_like_f']}°.{rain}"
    )
```

---

## `agent/world/flights.py`

```python
# agent/world/flights.py
# AeroDataBox API — flight status by flight number

import os
import httpx
from datetime import datetime
from agent.world import cache

API_KEY = os.getenv("AERODATABOX_API_KEY")
BASE = "https://aerodatabox.p.rapidapi.com"
HEADERS = {
    "X-RapidAPI-Key": API_KEY,
    "X-RapidAPI-Host": "aerodatabox.p.rapidapi.com",
}


async def get_flight_status(flight_number: str) -> dict:
    """
    Returns current status for a flight number e.g. 'DL 404', 'AA1234'.
    Strips spaces and normalizes input.
    """
    fn = flight_number.upper().replace(" ", "")
    cache_key = f"flight:{fn}"
    cached = cache.get(cache_key, "flight")
    if cached:
        return cached

    today = datetime.now().strftime("%Y-%m-%d")

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE}/flights/number/{fn}/{today}",
            headers=HEADERS,
            timeout=8.0
        )
        resp.raise_for_status()
        data = resp.json()

    if not data:
        return {"error": f"No flight data found for {flight_number}."}

    flight = data[0]
    dep = flight.get("departure", {})
    arr = flight.get("arrival", {})

    result = {
        "flight_number": fn,
        "status": flight.get("status", "unknown"),
        "origin": dep.get("airport", {}).get("name", "unknown"),
        "destination": arr.get("airport", {}).get("name", "unknown"),
        "scheduled_departure": dep.get("scheduledTime", {}).get("local"),
        "actual_departure": dep.get("actualTime", {}).get("local"),
        "scheduled_arrival": arr.get("scheduledTime", {}).get("local"),
        "delay_minutes": dep.get("delay", 0),
        "gate": dep.get("gate"),
        "terminal": dep.get("terminal"),
    }

    cache.set(cache_key, "flight", result)
    return result


def format_flight(f: dict) -> str:
    if "error" in f:
        return f["error"]

    status = f["status"].lower()
    delay = f["delay_minutes"]

    if status == "departed":
        return (
            f"{f['flight_number']} has departed {f['origin']}. "
            f"Scheduled to arrive at {f['destination']} at {f['scheduled_arrival']}."
        )
    if delay and delay > 0:
        return (
            f"{f['flight_number']} to {f['destination']} is delayed "
            f"by {delay} minutes. New departure around {f['actual_departure']}."
        )

    gate = f" Gate {f['gate']}." if f["gate"] else ""
    return (
        f"{f['flight_number']} to {f['destination']} is on time."
        f" Scheduled departure at {f['scheduled_departure']}.{gate}"
    )
```

---

## `agent/world/sports.py`

```python
# agent/world/sports.py
# SportsData.io — scores and standings by sport

import os
import httpx
from datetime import datetime
from agent.world import cache

KEYS = {
    "nfl": os.getenv("SPORTSDATA_NFL_KEY"),
    "nba": os.getenv("SPORTSDATA_NBA_KEY"),
    "mlb": os.getenv("SPORTSDATA_MLB_KEY"),
}

BASES = {
    "nfl": "https://api.sportsdata.io/v3/nfl/scores/json",
    "nba": "https://api.sportsdata.io/v3/nba/scores/json",
    "mlb": "https://api.sportsdata.io/v3/mlb/scores/json",
}

LOCAL_TEAMS = [
    t.strip() for t in os.getenv("LOCAL_SPORTS_TEAMS", "").split(",") if t.strip()
]


async def get_scores(sport: str, team: str | None = None) -> dict:
    """
    Returns recent and live game scores for a sport.
    If team is provided, filters to that team.
    Falls back to local teams from config if no team specified.
    """
    sport = sport.lower()
    if sport not in BASES:
        return {"error": f"Sport '{sport}' not supported. Try nfl, nba, or mlb."}

    today = datetime.now().strftime("%Y-%m-%d")
    cache_key = f"sports:{sport}:{team or 'all'}:{today}"
    cached = cache.get(cache_key, "sports")
    if cached:
        return cached

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASES[sport]}/ScoresByDate/{today}",
            params={"key": KEYS[sport]},
            timeout=6.0
        )
        resp.raise_for_status()
        games = resp.json()

    # Filter by team if specified
    target = team or next(iter(LOCAL_TEAMS), None)
    if target:
        games = [
            g for g in games
            if target.lower() in g.get("HomeTeam", "").lower()
            or target.lower() in g.get("AwayTeam", "").lower()
            or target.lower() in g.get("HomeTeamName", "").lower()
            or target.lower() in g.get("AwayTeamName", "").lower()
        ]

    result = {"sport": sport, "games": games, "date": today}
    cache.set(cache_key, "sports", result)
    return result


def format_scores(data: dict) -> str:
    if "error" in data:
        return data["error"]

    games = data.get("games", [])
    if not games:
        return f"No {data['sport'].upper()} games found for today."

    lines = []
    for g in games[:3]:  # cap at 3 games for spoken response
        home = g.get("HomeTeam", "?")
        away = g.get("AwayTeam", "?")
        hs = g.get("HomeScore")
        as_ = g.get("AwayScore")
        status = g.get("Status", "")

        if hs is not None and as_ is not None:
            lines.append(f"{away} {as_}, {home} {hs} — {status}")
        else:
            time = g.get("DateTime", "")
            lines.append(f"{away} at {home}, {time}")

    return " | ".join(lines)
```

---

## `agent/world/news.py`

```python
# agent/world/news.py
# NewsAPI.org — top headlines by category

import os
import httpx
from agent.world import cache

API_KEY = os.getenv("NEWSAPI_KEY")
BASE = "https://newsapi.org/v2"
LOCAL_CITY = os.getenv("LOCAL_CITY", "Atlanta")

CATEGORIES = ["general", "business", "technology", "sports", "entertainment", "health"]


async def get_headlines(
    category: str = "general",
    local: bool = False,
    count: int = 3
) -> dict:
    """
    Returns top headlines. Set local=True for city-specific news.
    """
    cache_key = f"news:{category}:{'local' if local else 'national'}"
    cached = cache.get(cache_key, "news")
    if cached:
        return cached

    params = {
        "apiKey": API_KEY,
        "pageSize": count,
        "language": "en",
    }

    if local:
        params["q"] = LOCAL_CITY
        params["sortBy"] = "publishedAt"
        endpoint = f"{BASE}/everything"
    else:
        params["category"] = category if category in CATEGORIES else "general"
        params["country"] = "us"
        endpoint = f"{BASE}/top-headlines"

    async with httpx.AsyncClient() as client:
        resp = await client.get(endpoint, params=params, timeout=6.0)
        resp.raise_for_status()
        data = resp.json()

    articles = [
        {
            "title": a["title"],
            "source": a["source"]["name"],
            "description": a.get("description", ""),
        }
        for a in data.get("articles", [])[:count]
        if a.get("title") and "[Removed]" not in a["title"]
    ]

    result = {"category": category, "local": local, "articles": articles}
    cache.set(cache_key, "news", result)
    return result


def format_headlines(data: dict) -> str:
    articles = data.get("articles", [])
    if not articles:
        return "No headlines available right now."

    # For spoken output — just titles, no descriptions
    titles = [f"{a['title']} — {a['source']}" for a in articles]
    return " | ".join(titles)
```

---

## `agent/world/places.py`

```python
# agent/world/places.py
# Google Places API — POI near current or next stop

import os
import httpx
from agent.world import cache

API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")
BASE = "https://maps.googleapis.com/maps/api/place"

PLACE_TYPES = {
    "coffee": "cafe",
    "food": "restaurant",
    "restaurant": "restaurant",
    "pharmacy": "pharmacy",
    "grocery": "grocery_or_supermarket",
    "transit": "transit_station",
    "atm": "atm",
    "hotel": "lodging",
}


async def get_nearby(
    lat: float,
    lng: float,
    query: str,
    radius_m: int = 500
) -> dict:
    """
    Returns POI near a lat/lng. Query is a natural language type
    e.g. 'coffee', 'food', 'pharmacy'.
    """
    place_type = PLACE_TYPES.get(query.lower(), "point_of_interest")
    cache_key = f"places:{lat:.3f},{lng:.3f}:{place_type}"
    cached = cache.get(cache_key, "places")
    if cached:
        return cached

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE}/nearbysearch/json",
            params={
                "location": f"{lat},{lng}",
                "radius": radius_m,
                "type": place_type,
                "key": API_KEY,
            },
            timeout=6.0
        )
        resp.raise_for_status()
        data = resp.json()

    places = [
        {
            "name": p["name"],
            "vicinity": p.get("vicinity", ""),
            "rating": p.get("rating"),
            "open_now": p.get("opening_hours", {}).get("open_now"),
        }
        for p in data.get("results", [])[:3]
    ]

    result = {"query": query, "places": places}
    cache.set(cache_key, "places", result)
    return result


def format_places(data: dict) -> str:
    places = data.get("places", [])
    if not places:
        return f"No {data['query']} spots found nearby."

    lines = []
    for p in places:
        open_str = ""
        if p["open_now"] is True:
            open_str = ", open now"
        elif p["open_now"] is False:
            open_str = ", currently closed"
        rating = f" ({p['rating']}★)" if p["rating"] else ""
        lines.append(f"{p['name']}{rating}{open_str}")

    return "Nearby: " + ", ".join(lines) + "."
```

---

## Claude Tool Definitions — add to `agent/llm.py`

```python
WORLD_TOOLS = [
    {
        "name": "get_weather",
        "description": (
            "Get current weather for a location. If the rider says 'the weather' "
            "without specifying a place, use the next stop or destination from ride context."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City, neighborhood, or stop name"
                }
            },
            "required": ["location"]
        }
    },
    {
        "name": "get_flight_status",
        "description": "Get live status for a flight by flight number e.g. 'DL404', 'AA 1234'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "flight_number": {
                    "type": "string",
                    "description": "Flight number e.g. DL404, AA 1234, UA567"
                }
            },
            "required": ["flight_number"]
        }
    },
    {
        "name": "get_sports_scores",
        "description": (
            "Get today's scores for a sport. If no team is specified, "
            "defaults to local teams. Supports nfl, nba, mlb."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sport": {
                    "type": "string",
                    "enum": ["nfl", "nba", "mlb"],
                    "description": "Sport league"
                },
                "team": {
                    "type": "string",
                    "description": "Optional team name to filter results"
                }
            },
            "required": ["sport"]
        }
    },
    {
        "name": "get_news",
        "description": "Get top news headlines. Optionally filter by category or get local city news.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["general", "business", "technology", "sports",
                             "entertainment", "health"],
                    "description": "News category"
                },
                "local": {
                    "type": "boolean",
                    "description": "If true, returns news local to the current city"
                }
            }
        }
    },
    {
        "name": "get_nearby_places",
        "description": (
            "Find points of interest near the current or next stop. "
            "Use when rider asks about food, coffee, pharmacies, etc. near their stop."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Type of place e.g. coffee, food, pharmacy, atm"
                },
                "stop": {
                    "type": "string",
                    "description": "Stop name to search near — use next_stop from ride context if not specified"
                }
            },
            "required": ["query"]
        }
    }
]
```

---

## Tool Call Handler — add to `agent/llm.py`

```python
from agent.world import weather, flights, sports, news, places

async def handle_world_tool(name: str, inputs: dict, ride_context: dict) -> str:
    try:
        if name == "get_weather":
            location = inputs.get("location") or ride_context.get("next_stop")
            result = await weather.get_weather(location)
            return weather.format_weather(result)

        elif name == "get_flight_status":
            result = await flights.get_flight_status(inputs["flight_number"])
            return flights.format_flight(result)

        elif name == "get_sports_scores":
            result = await sports.get_scores(
                sport=inputs["sport"],
                team=inputs.get("team")
            )
            return sports.format_scores(result)

        elif name == "get_news":
            result = await news.get_headlines(
                category=inputs.get("category", "general"),
                local=inputs.get("local", False)
            )
            return news.format_headlines(result)

        elif name == "get_nearby_places":
            # Resolve stop coords from ride context
            stop = inputs.get("stop") or ride_context.get("next_stop")
            coords = ride_context.get("stop_coords", {}).get(stop)
            if not coords:
                return f"I don't have location data for {stop} yet."
            result = await places.get_nearby(
                lat=coords["lat"],
                lng=coords["lng"],
                query=inputs["query"]
            )
            return places.format_places(result)

    except httpx.TimeoutException:
        return "That's taking too long — try again in a moment."
    except httpx.HTTPStatusError as e:
        return f"Couldn't fetch that right now ({e.response.status_code})."
    except Exception as e:
        return "Something went wrong fetching that data."
```

---

## Proactive World Query Triggers — add to `agent/proactive.py`

```python
# Add these to the existing trigger list in proactive.py

{
    "id": "destination_weather",
    "condition": lambda ctx: ctx.eta_seconds < 300 and not ctx.triggers_fired["destination_weather"],
    "message": "[PROACTIVE] The rider is about to arrive. Check and mention the weather at their destination stop without being asked.",
    "fired": False,
},
{
    "id": "morning_news",
    "condition": lambda ctx: 6 <= ctx.hour_of_day <= 9 and ctx.elapsed_seconds < 60 and not ctx.triggers_fired["morning_news"],
    "message": "[PROACTIVE] It's morning. Offer a brief news headline summary for the ride.",
    "fired": False,
},
```

---

## Ride Context — add stop coords to `agent/context.py`

```python
@dataclass
class RideContext:
    # ... existing fields ...
    stop_coords: dict[str, dict]  # { "Civic Center": { "lat": 37.779, "lng": -122.414 } }
```

Populate from your route configuration — these are fixed per stop on a PRT network so can be hardcoded in a route config file rather than looked up dynamically.

---

## Session Reset — add to `agent/main.py`

```python
from agent.world import cache as world_cache

async def start_ride_session():
    world_cache.clear()   # clear stale data from previous ride
    echo_guard.clear()
    # ... rest of session init
```

---

## File Placement

```
transit-agent/
└── agent/
    └── world/
        ├── __init__.py
        ├── cache.py
        ├── weather.py
        ├── flights.py
        ├── sports.py
        ├── news.py
        └── places.py
```
