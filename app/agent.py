# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import base64
import datetime
import json
import os
from typing import Any, Dict, List, Optional
import requests
from dotenv import load_dotenv
from google.cloud import firestore, storage

from a2ui.schema.manager import A2uiSchemaManager
from a2ui.basic_catalog.provider import BasicCatalog

from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.code_executors import AgentEngineSandboxCodeExecutor
from google.adk.code_executors.code_execution_utils import CodeExecutionInput
from google.adk.memory import VertexAiMemoryBankService
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google import genai
from google.genai import types

try:
    from .a2ui_utils import a2ui_callback
except ImportError:
    from a2ui_utils import a2ui_callback

load_dotenv()

# Hardcoded GCP Project ID and Bucket Name
PROJECT_ID = "qwiklabs-gcp-02-570bfbc4645a"
BUCKET_NAME = "run-for-your-life-assets-qwiklabs-gcp-02-570bfbc4645a"

# Load Reasoning Engine / Agent Engine Resource Name from deployment_metadata.json
deployment_meta_path = os.path.join(
    os.path.dirname(__file__), "..", "deployment_metadata.json"
)
agent_engine_resource_name = None
if os.path.exists(deployment_meta_path):
    with open(deployment_meta_path) as f:
        meta = json.load(f)
        agent_engine_resource_name = meta.get("remote_agent_runtime_id")

code_executor = None
if agent_engine_resource_name:
    code_executor = AgentEngineSandboxCodeExecutor(
        agent_engine_resource_name=agent_engine_resource_name
    )

memory_bank_id = (
    agent_engine_resource_name.split("/")[-1]
    if agent_engine_resource_name
    else None
)


def memory_bank_service_builder():
    """Provides VertexAiMemoryBankService for deployed agent execution."""
    if memory_bank_id:
        return VertexAiMemoryBankService(
            project=PROJECT_ID,
            location="us-central1",
            agent_engine_id=memory_bank_id,
        )
    return None


# Initialize Firestore and Cloud Storage Clients
db = firestore.Client(project=PROJECT_ID)
run_logs_ref = db.collection("run_logs")
badges_ref = db.collection("badges")
storage_client = storage.Client(project=PROJECT_ID)


async def generate_memories_callback(callback_context: CallbackContext):
    """WRITE: after each agent turn, extract and persist durable session facts into Memory Bank."""
    try:
        await callback_context.add_session_to_memory()
    except Exception as e:
        pass
    return None


def run_python_code(code: str, tool_context: ToolContext) -> str:
    """Executes Python code inside the secure Agent Engine sandbox environment and returns the execution output.

    Args:
        code: Python code string to execute (e.g., 'print(24.5 * (10 / 5) ** 1.06)').
        tool_context: ADK ToolContext to retrieve invocation context and session state.

    Returns:
        The execution stdout or stderr result from the Agent Engine sandbox.
    """
    if not code_executor:
        return "Error: AgentEngineSandboxCodeExecutor is not initialized."

    try:
        inv_context = tool_context.get_invocation_context()
        execution_result = code_executor.execute_code(
            invocation_context=inv_context,
            code_execution_input=CodeExecutionInput(code=code),
        )
        stdout = execution_result.stdout or ""
        stderr = execution_result.stderr or ""
        if stdout:
            return f"🐍 Sandbox Output:\n{stdout.strip()}"
        elif stderr:
            return f"⚠️ Sandbox Error:\n{stderr.strip()}"
        return "Code executed successfully with no output."
    except Exception as e:
        return f"Error executing Python code in Agent Engine sandbox: {str(e)}"


async def generate_running_motivation_image(
    prompt_description: str, tool_context: ToolContext
) -> str:
    """Generates a motivational running image or artwork using gemini-3.1-flash-lite-image in the global region. Saves it as an artifact and uploads to public Cloud Storage.

    Args:
        prompt_description: Description of the running image to generate (e.g., 'Runner at sunrise in Central Park', 'Golden marathon finish line').
        tool_context: ADK ToolContext used to save the generated image as an artifact in the Playground.

    Returns:
        The public HTTPS Cloud Storage URL of the generated image asset.
    """
    try:
        filename = f"running_image_{int(datetime.datetime.now(datetime.timezone.utc).timestamp())}.jpg"

        # Initialize GenAI client in location="global"
        global_genai_client = genai.Client(
            vertexai=True, project=PROJECT_ID, location="global"
        )

        # Generate image using gemini-3.1-flash-lite-image
        res = global_genai_client.models.generate_content(
            model="gemini-3.1-flash-lite-image", contents=prompt_description
        )

        part = res.candidates[0].content.parts[0]
        image_bytes = part.inline_data.data
        mime_type = part.inline_data.mime_type or "image/jpeg"

        # 1. Save artifact to ADK ToolContext (Playground Artifacts panel)
        artifact_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        await tool_context.save_artifact(filename=filename, artifact=artifact_part)

        # 2. Upload same image bytes to public Cloud Storage bucket
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(f"generated_images/{filename}")
        blob.upload_from_string(image_bytes, content_type=mime_type)
        public_url = (
            f"https://storage.googleapis.com/{BUCKET_NAME}/generated_images/{filename}"
        )

        return (
            f"🖼️ Generated Running Image:\n"
            f"• Prompt: {prompt_description}\n"
            f"• Saved Artifact Name: {filename}\n"
            f"• Public Cloud Storage URL: {public_url}"
        )
    except Exception as e:
        return f"Error generating running image: {str(e)}"


async def generate_running_motivation_video(
    prompt_description: str, tool_context: ToolContext
) -> str:
    """Generates a short motivational running video using Google's Omni model (gemini-omni-flash-preview) in the global region.
    Saves it as an artifact and uploads to public Cloud Storage bucket.

    Args:
        prompt_description: Description of the running video to generate (e.g., 'Runner sprinting across the finish line at sunset', 'Cinematic trail run in mountain forest').
        tool_context: ADK ToolContext used to save the generated video as an artifact in the Playground.

    Returns:
        The public HTTPS Cloud Storage URL of the generated video asset.
    """
    try:
        filename = f"running_video_{int(datetime.datetime.now(datetime.timezone.utc).timestamp())}.mp4"

        # Initialize GenAI client in location="global"
        global_genai_client = genai.Client(
            vertexai=True, project=PROJECT_ID, location="global"
        )

        # Generate video using gemini-omni-flash-preview via Interactions API
        interaction = global_genai_client.interactions.create(
            model="gemini-omni-flash-preview",
            input=prompt_description,
        )

        output_video = getattr(interaction, "output_video", None)
        if not output_video:
            return "Error: No video output returned by gemini-omni-flash-preview."

        raw_data = getattr(output_video, "data", None)
        if isinstance(raw_data, str):
            video_bytes = base64.b64decode(raw_data)
        elif isinstance(raw_data, (bytes, bytearray)):
            video_bytes = bytes(raw_data)
        else:
            return "Error: Video bytes data was not found in interaction output."

        mime_type = getattr(output_video, "mime_type", None) or "video/mp4"

        # 1. Save artifact to ADK ToolContext (Playground Artifacts panel)
        artifact_part = types.Part.from_bytes(data=video_bytes, mime_type=mime_type)
        await tool_context.save_artifact(filename=filename, artifact=artifact_part)

        # 2. Upload same video bytes to public Cloud Storage bucket
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(f"generated_videos/{filename}")
        blob.upload_from_string(video_bytes, content_type=mime_type)
        public_url = (
            f"https://storage.googleapis.com/{BUCKET_NAME}/generated_videos/{filename}"
        )

        return (
            f"🎬 Generated Running Video:\n"
            f"• Prompt: {prompt_description}\n"
            f"• Saved Artifact Name: {filename}\n"
            f"• Public Cloud Storage URL: {public_url}"
        )
    except Exception as e:
        return f"Error generating running video: {str(e)}"


def geocode_address(address: str) -> str:
    """Uses Google Maps Geocoding API to convert an address or place name into exact geographic coordinates (latitude and longitude).

    Args:
        address: The address or place name to geocode (e.g., 'Central Park, New York', 'Golden Gate Park, San Francisco').

    Returns:
        Formatted address, latitude, and longitude.
    """
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return "Error: GOOGLE_MAPS_API_KEY is missing from environment variables."

    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={requests.utils.quote(address)}&key={api_key}"
    try:
        res = requests.get(url, timeout=5).json()
        if res.get("status") == "OK" and res.get("results"):
            first = res["results"][0]
            fmt_addr = first.get("formatted_address", address)
            loc = first["geometry"]["location"]
            lat, lng = loc["lat"], loc["lng"]
            return f"📍 Geocoded '{address}':\n• Formatted Address: {fmt_addr}\n• Coordinates: Latitude {lat}, Longitude {lng}"
        return f"Could not find coordinates for address '{address}'. Status: {res.get('status')}"
    except Exception as e:
        return f"Error calling Google Maps Geocoding API: {str(e)}"


def search_nearby_places(
    latitude: float,
    longitude: float,
    place_type: str = "park",
    radius_meters: float = 3000.0,
) -> str:
    """Uses Google Places API (New) to search for nearby places (like parks, athletic fields, or sports venues) around a coordinate location.

    Args:
        latitude: Center latitude coordinate.
        longitude: Center longitude coordinate.
        place_type: Type of place to search for (e.g., 'park', 'athletic_field', 'sports_complex').
        radius_meters: Search radius in meters (default 3000 meters / 3 km).

    Returns:
        A formatted list of nearby places with name, formatted address, location coordinates, and rating.
    """
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return "Error: GOOGLE_MAPS_API_KEY is missing from environment variables."

    url = "https://places.googleapis.com/v1/places:searchNearby"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location,places.rating,places.types",
    }
    body = {
        "includedTypes": [place_type],
        "locationRestriction": {
            "circle": {
                "center": {"latitude": latitude, "longitude": longitude},
                "radius": float(radius_meters),
            }
        },
        "maxResultCount": 5,
    }

    try:
        res = requests.post(url, json=body, headers=headers, timeout=5).json()
        places = res.get("places", [])

        if not places:
            return f"No nearby places of type '{place_type}' found within {radius_meters}m of ({latitude}, {longitude})."

        results = []
        for p in places:
            name = p.get("displayName", {}).get("text", "Unknown Place")
            addr = p.get("formattedAddress", "N/A")
            loc = p.get("location", {})
            p_lat, p_lng = loc.get("latitude", "N/A"), loc.get("longitude", "N/A")
            rating = p.get("rating", "N/A")

            results.append(
                f"- 🌲 {name} (Rating: {rating}⭐️)\n  Address: {addr}\n  Location: Lat {p_lat}, Lng {p_lng}"
            )

        return (
            f"📍 Found {len(places)} nearby '{place_type}' locations around ({latitude}, {longitude}):\n"
            + "\n".join(results)
        )
    except Exception as e:
        return f"Error calling Google Places API (New): {str(e)}"


def get_outdoor_running_weather(location: str = "New York") -> str:
    """Fetches real live outdoor weather metrics (temperature, humidity, rain, wind) for a given city to assess running conditions.

    Args:
        location: City or location name to check weather for (e.g., 'New York', 'San Francisco', 'London').

    Returns:
        Real weather metrics and an assessment on whether conditions are favorable for outdoor running.
    """
    try:
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={requests.utils.quote(location)}&count=1"
        geo_resp = requests.get(geo_url, timeout=5).json()

        if not geo_resp.get("results"):
            return f"Could not locate weather data for '{location}'."

        first_res = geo_resp["results"][0]
        lat, lon = first_res["latitude"], first_res["longitude"]
        city_fullname = f"{first_res['name']}, {first_res.get('admin1', '')} ({first_res.get('country', '')})"

        weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,precipitation,weather_code,wind_speed_10m"
        weather_data = requests.get(weather_url, timeout=5).json().get("current", {})

        temp_c = weather_data.get("temperature_2m", "N/A")
        humidity = weather_data.get("relative_humidity_2m", "N/A")
        precip_mm = weather_data.get("precipitation", 0.0)
        wind_kmh = weather_data.get("wind_speed_10m", "N/A")

        if precip_mm > 0.5:
            assessment = "⚠️ Active rain detected. Consider an indoor cardio session or waterproof running gear."
        elif isinstance(temp_c, (int, float)) and temp_c > 30:
            assessment = "🔥 High temperature alert. Hydrate heavily and prefer early morning / evening runs."
        elif isinstance(temp_c, (int, float)) and temp_c < 0:
            assessment = "❄️ Sub-zero temperature. Dress in thermal layers."
        else:
            assessment = "✅ Great conditions for an outdoor run!"

        return (
            f"🌤️ Real Weather for {city_fullname}:\n"
            f"• Temperature: {temp_c}°C\n"
            f"• Humidity: {humidity}%\n"
            f"• Precipitation: {precip_mm} mm\n"
            f"• Wind Speed: {wind_kmh} km/h\n"
            f"• Running Suitability: {assessment}"
        )
    except Exception as e:
        return f"Error fetching live weather data for '{location}': {str(e)}"


def log_run(
    distance_km: float,
    duration_minutes: int,
    pre_run_mood: str,
    post_run_mood: str,
    energy_level: int,
    skip_reason: Optional[str] = None,
    notes: str = "",
) -> str:
    """Logs a running session or a skipped run entry to Firestore.

    Args:
        distance_km: Distance ran in kilometers (0.0 if skipped).
        duration_minutes: Total duration of the run in minutes (0 if skipped).
        pre_run_mood: Feeling or mindset before the run (e.g., 'Stressed', 'Motivated').
        post_run_mood: Feeling or mindset after the run (e.g., 'Refreshed', 'Tired').
        energy_level: Self-reported energy level on a scale from 1 to 10.
        skip_reason: Optional reason if the run was skipped or shortened.
        notes: Additional notes or context about the session/day.

    Returns:
        A confirmation message with the logged run ID and details.
    """
    today_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    doc_id = f"run_{int(datetime.datetime.now(datetime.timezone.utc).timestamp())}"

    if distance_km > 0 and duration_minutes > 0:
        pace_decimal = duration_minutes / distance_km
        pace_minutes = int(pace_decimal)
        pace_seconds = int((pace_decimal - pace_minutes) * 60)
        average_pace = f"{pace_minutes}:{pace_seconds:02d} min/km"
        performance_score = min(100, int(70 + (energy_level * 2) + min(15, distance_km * 2)))
    else:
        average_pace = "N/A"
        performance_score = 40 if skip_reason else 50

    run_data = {
        "id": doc_id,
        "date": today_str,
        "distance_km": float(distance_km),
        "duration_minutes": int(duration_minutes),
        "average_pace": average_pace,
        "performance_score": performance_score,
        "pre_run_mood": pre_run_mood,
        "post_run_mood": post_run_mood,
        "energy_level": int(energy_level),
        "skip_reason": skip_reason if skip_reason else None,
        "notes": notes,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    run_logs_ref.document(doc_id).set(run_data)
    return f"Logged run entry '{doc_id}' for {today_str}: {distance_km} km in {duration_minutes} mins (Pace: {average_pace}, Energy: {energy_level}/10, Pre-mood: {pre_run_mood}, Post-mood: {post_run_mood})."


def get_run_history(limit: int = 10) -> str:
    """Retrieves recent running and mindset logs from Firestore.

    Args:
        limit: The maximum number of recent run logs to retrieve (default 10).

    Returns:
        A formatted summary list of recent run logs and skipped run patterns.
    """
    docs = run_logs_ref.limit(limit).stream()
    logs: List[Dict[str, Any]] = [doc.to_dict() for doc in docs]

    if not logs:
        return "No running logs found in Firestore database."

    logs.sort(key=lambda x: x.get("date", ""), reverse=True)

    formatted_runs = []
    for log in logs:
        dist = log.get("distance_km", 0.0)
        dur = log.get("duration_minutes", 0)
        pace = log.get("average_pace", "N/A")
        score = log.get("performance_score", "N/A")
        pre = log.get("pre_run_mood", "Unknown")
        post = log.get("post_run_mood", "Unknown")
        energy = log.get("energy_level", "N/A")
        skip = log.get("skip_reason")
        date_str = log.get("date", "Unknown date")

        skip_info = f" | Skipped Reason: {skip}" if skip else ""
        formatted_runs.append(
            f"- [{date_str}] {dist} km in {dur} mins | Pace: {pace} | Score: {score}/100 | Energy: {energy}/10 | Pre: {pre} -> Post: {post}{skip_info}"
        )

    return f"Recent Run History ({len(logs)} entries):\n" + "\n".join(formatted_runs)


def analyze_mindset_and_patterns() -> str:
    """Analyzes overall performance trends, mood correlations, and common skip reasons from stored run logs.

    Returns:
        An analysis report connecting sports performance with mood and life events.
    """
    docs = list(run_logs_ref.stream())
    logs = [doc.to_dict() for doc in docs]

    if not logs:
        return "Not enough data to analyze patterns yet."

    total_runs = len(logs)
    completed_runs = [l for l in logs if l.get("distance_km", 0) > 0]
    skipped_runs = [l for l in logs if l.get("skip_reason")]

    total_distance = sum(l.get("distance_km", 0.0) for l in completed_runs)
    avg_energy = sum(l.get("energy_level", 5) for l in logs) / total_runs

    skip_reasons = [l.get("skip_reason") for l in skipped_runs if l.get("skip_reason")]

    summary = (
        f"Mindset & Performance Analysis across {total_runs} entries:\n"
        f"- Total Distance Completed: {total_distance:.1f} km across {len(completed_runs)} active runs.\n"
        f"- Average Reported Energy: {avg_energy:.1f}/10.\n"
        f"- Skipped Sessions Count: {len(skipped_runs)}.\n"
    )

    if skip_reasons:
        summary += f"- Identified Skip Reasons / Life Blockers: {', '.join(skip_reasons)}.\n"

    summary += (
        "Pattern Insight: User shows high mood improvement post-run even when starting with stress or low energy."
    )

    return summary


def recommend_adaptive_workout(
    available_minutes: int,
    energy_level: int,
    is_outdoor_possible: bool = True,
    target_focus: str = "general",
) -> str:
    """Provides adaptive workout options (Option A & Option B) based on available time window, energy level, and indoor/outdoor constraints.

    Args:
        available_minutes: Time available for training in minutes (e.g., 15, 30, 45, 60).
        energy_level: Current self-reported energy level from 1 (exhausted) to 10 (peak energy).
        is_outdoor_possible: True if outdoor running is feasible, False if restricted to indoor or bad weather.
        target_focus: Optional focus like 'cardio', 'stamina', 'recovery', or 'general'.

    Returns:
        A detailed recommendation containing Option A (Primary) and Option B (Light Alternative).
    """
    time_str = f"{available_minutes} minutes"

    if available_minutes <= 20 or not is_outdoor_possible:
        option_a_title = "Option A: 15-Minute Indoor Agile Cardio Burst"
        option_a_desc = (
            f"Designed for your tight {time_str} window indoors:\n"
            "• 3 mins Warmup: Arm circles, light bouncing, torso twists\n"
            "• 10 mins High-Yield Circuit (30s work / 15s rest x 3 rounds):\n"
            "   - Jumping Jacks / High Knees\n"
            "   - Mountain Climbers\n"
            "   - Shadow Boxing / Fast Footwork\n"
            "   - Bodyweight Squats / Pulse Jumps\n"
            "• 2 mins Cooldowns & Deep Diaphragmatic Breathing."
        )
        option_b_title = "Option B: 10-Minute Mobility & Core Energizer"
        option_b_desc = (
            "A low-friction indoor session to keep momentum without exhaustion:\n"
            "• 4 mins Plank & Cat-Cow Flow\n"
            "• 4 mins Hip Opener & Runner Leg Swings\n"
            "• 2 mins Mindset Reset."
        )
    elif energy_level <= 4:
        option_a_title = f"Option A: {min(30, available_minutes)}-Minute Low-Impact Active Recovery Run"
        option_a_desc = (
            f"Gently matches your low energy ({energy_level}/10):\n"
            "• 5 mins Warm Walk\n"
            "• 20 mins Easy Jog / Walk Intervals (2 min jog / 1 min easy walk)\n"
            "• 5 mins Mindful Stretches."
        )
        option_b_title = "Option B: 15-Minute Brisk Walk & Outdoor Fresh Air Reset"
        option_b_desc = "No pressure run—just a brisk 15-minute walk to clear your mind and boost oxygen."
    else:
        option_a_title = f"Option A: {available_minutes}-Minute Progressive Outdoor Pace Session"
        option_a_desc = (
            f"Capitalizes on your solid energy ({energy_level}/10):\n"
            "• 5 mins Dynamic Warmup\n"
            f"• {available_minutes - 10} mins Progressive Run (start at easy pace, increase speed final 10 mins)\n"
            "• 5 mins Cool Down & Hydration."
        )
        option_b_title = f"Option B: {min(25, available_minutes)}-Minute Tempo Intervals"
        option_b_desc = "3 x 5-minute tempo efforts with 2-minute recovery walks."

    return (
        f"🏃 Adaptive Training Recommendation ({time_str} available | Energy: {energy_level}/10):\n\n"
        f"🎯 {option_a_title}\n{option_a_desc}\n\n"
        f"💡 {option_b_title}\n{option_b_desc}\n\n"
        "Which option fits your schedule best today?"
    )


def generate_achievement_badge(
    animal_type: str,
    badge_title: str,
    achievement_description: str,
) -> str:
    """Generates a cute, comic, colorful agile animal achievement badge image and uploads it to public Cloud Storage.

    Args:
        animal_type: Agile animal theme - 'cheetah' (speed), 'squirrel' (15-min quick sprint), 'gazelle' (endurance/distance), 'mountain_goat' (grit/climb), or 'fox' (consistency).
        badge_title: Short title displayed on the badge ribbon (e.g., 'SPEED CHEETAH 5K', 'FLASH SQUIRREL 15M').
        achievement_description: Explanation of what milestone earned this badge.

    Returns:
        The public HTTP URL of the generated badge asset and achievement details.
    """
    animal = animal_type.lower().strip()
    badge_id = f"badge_{animal}_{int(datetime.datetime.now(datetime.timezone.utc).timestamp())}"

    if "squirrel" in animal:
        bg_start, bg_end = "#FF9800", "#F4511E"
        animal_color = "#E65100"
        title_text = badge_title.upper() if badge_title else "FLASH SQUIRREL"
        feature_svg = '<path d="M 120 100 Q 90 70 80 110 Q 70 140 110 130 Z" fill="#E65100"/>'
    elif "gazelle" in animal or "antelope" in animal:
        bg_start, bg_end = "#00B0FF", "#3F51B5"
        animal_color = "#FB8C00"
        title_text = badge_title.upper() if badge_title else "GAZELLE ENDURANCE"
        feature_svg = '<path d="M 130 90 L 125 50 M 170 90 L 175 50" stroke="#3E2723" stroke-width="5" stroke-linecap="round"/>'
    elif "mountain_goat" in animal or "goat" in animal:
        bg_start, bg_end = "#00E676", "#1DE9B6"
        animal_color = "#ECEFF1"
        title_text = badge_title.upper() if badge_title else "MOUNTAIN CLIMBER"
        feature_svg = '<path d="M 135 85 Q 120 55 110 75 M 165 85 Q 180 55 190 75" stroke="#78909C" stroke-width="6" stroke-linecap="round"/>'
    elif "fox" in animal:
        bg_start, bg_end = "#FF3D00", "#FFD600"
        animal_color = "#FF6D00"
        title_text = badge_title.upper() if badge_title else "GRIT FOX HERO"
        feature_svg = '<polygon points="100,100 80,60 115,80" fill="#FF6D00"/><polygon points="200,100 220,60 185,80" fill="#FF6D00"/>'
    else:
        bg_start, bg_end = "#FF512F", "#DD2476"
        animal_color = "#FFA726"
        title_text = badge_title.upper() if badge_title else "LIGHTNING CHEETAH"
        feature_svg = '<circle cx="115" cy="120" r="5" fill="#212121"/><circle cx="185" cy="120" r="5" fill="#212121"/><circle cx="150" cy="95" r="5" fill="#212121"/>'

    svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 320" width="320" height="320">
  <defs>
    <linearGradient id="bg_{badge_id}" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="{bg_start}"/>
      <stop offset="100%" stop-color="{bg_end}"/>
    </linearGradient>
    <linearGradient id="ring_{badge_id}" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#FFE000"/>
      <stop offset="100%" stop-color="#FFAB00"/>
    </linearGradient>
  </defs>
  <circle cx="160" cy="160" r="148" fill="url(#bg_{badge_id})" stroke="#FFFFFF" stroke-width="8" />
  <circle cx="160" cy="160" r="128" fill="none" stroke="url(#ring_{badge_id})" stroke-width="6" stroke-dasharray="10 6" />
  {feature_svg}
  <circle cx="160" cy="145" r="65" fill="{animal_color}"/>
  <circle cx="110" cy="95" r="20" fill="{animal_color}"/>
  <circle cx="110" cy="95" r="10" fill="#FF8A80"/>
  <circle cx="210" cy="95" r="20" fill="{animal_color}"/>
  <circle cx="210" cy="95" r="10" fill="#FF8A80"/>
  <ellipse cx="160" cy="160" rx="32" ry="22" fill="#FFFFFF"/>
  <circle cx="140" cy="140" r="10" fill="#212121"/>
  <circle cx="180" cy="140" r="10" fill="#212121"/>
  <circle cx="143" cy="137" r="3.5" fill="#FFFFFF"/>
  <circle cx="183" cy="137" r="3.5" fill="#FFFFFF"/>
  <polygon points="160,152 152,163 168,163" fill="#E91E63"/>
  <path d="M 152 168 Q 160 174 168 168" stroke="#212121" stroke-width="3" fill="none" stroke-linecap="round"/>
  <rect x="25" y="232" width="270" height="48" rx="16" fill="#1A237E" stroke="#FFFFFF" stroke-width="3"/>
  <text x="160" y="263" font-family="'Comic Sans MS', Arial, sans-serif" font-weight="bold" font-size="18" fill="#FFEB3B" text-anchor="middle">{title_text}</text>
</svg>"""

    bucket = storage_client.bucket(BUCKET_NAME)
    blob = bucket.blob(f"badges/{badge_id}.svg")
    blob.upload_from_string(svg_content, content_type="image/svg+xml")
    public_url = f"https://storage.googleapis.com/{BUCKET_NAME}/badges/{badge_id}.svg"

    badge_doc = {
        "badge_id": badge_id,
        "animal_type": animal,
        "title": title_text,
        "description": achievement_description,
        "public_url": public_url,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    badges_ref.document(badge_id).set(badge_doc)

    return (
        f"🏆 Achievement Badge Unlocked: '{title_text}'!\n"
        f"• Animal Mascot: {animal.capitalize()} (Agile & Energetic)\n"
        f"• Achievement: {achievement_description}\n"
        f"• Public Badge Image URL: {public_url}"
    )


# Build A2UI System Prompt (Version 0.8 with Basic Catalog)
schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

a2ui_instruction = schema_manager.generate_system_prompt(
    role_description=(
        "You are 'Run For Your Life', a supportive AI running and mindset coach. "
        "You help users log runs, track feelings, geocode locations (`geocode_address`), find nearby running parks/tracks (`search_nearby_places`), "
        "check live weather (`get_outdoor_running_weather`), generate running motivation imagery (`generate_running_motivation_image`), "
        "generate running motivation video clips (`generate_running_motivation_video`), "
        "recommend adaptive workouts (`recommend_adaptive_workout`), and award cute agile animal badges (`generate_achievement_badge`). "
        "You remember user preferences, stated goals, injury history, and runner details across sessions to personalize coaching. "
        "When performing math or calculations (such as pace calculations, Riegel race finish time projections, split targets, or Karvonen heart rate zones), "
        "use your `run_python_code` tool to execute Python code safely inside the Agent Engine sandbox."
    ),
    workflow_description=(
        "Analyze the request, call tools when necessary, and return structured UI surfaces when presenting workout options, weather reports, run logs, or coaching summaries."
    ),
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
        "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
        "nothing in adk web). "
        "You may include one Image component, but only when you have a public https "
        "URL for the image (for example the URL an image tool returns after uploading "
        "to a public bucket). Set the Image url to that exact https link, for example "
        '{"Image": {"url": {"literalString": "https://..."}}}. Never point an '
        "Image at a bare filename, an artifact name, or a non-http(s) path. If you do "
        "not have a public URL, add a short Text line noting the image instead. "
        "No markdown in text; use the usageHint property ('h1', 'h2', 'body') for "
        "headings and emphasis. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in "
        "<a2a_datapart_json> tags or 'kind'/'data'/'metadata' objects."
    ),
    include_schema=True,
    include_examples=True,
)


root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-2.5-flash",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    code_executor=code_executor,
    instruction=a2ui_instruction,
    tools=[
        PreloadMemoryTool(),
        run_python_code,
        generate_running_motivation_image,
        generate_running_motivation_video,
        geocode_address,
        search_nearby_places,
        get_outdoor_running_weather,
        log_run,
        get_run_history,
        analyze_mindset_and_patterns,
        recommend_adaptive_workout,
        generate_achievement_badge,
    ],
    after_agent_callback=generate_memories_callback,
    after_model_callback=a2ui_callback,
)

app = App(
    root_agent=root_agent,
    name="app",
)
