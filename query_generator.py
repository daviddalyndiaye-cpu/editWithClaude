import json
import time
import httpx
from google import genai
from google.genai import types
from google.genai.errors import APIError
from config import GEMINI_API_KEY, GEMINI_QUERY_MODEL, QUERY_WORD_RANGE

MAX_RETRIES = 4
RETRY_BASE_DELAY = 5  # seconds
DELAY_BETWEEN_CALLS = 2  # seconds — throttle to avoid server disconnects

client = genai.Client(api_key=GEMINI_API_KEY)

SYSTEM_INSTRUCTION = (
    "You are a professional video editor choosing B-roll footage from Pexels. "
    "You will receive a FULL TRANSCRIPT for context and a HIGHLIGHTED SEGMENT to generate queries for.\n\n"
    "Output a JSON object with exactly these keys:\n"
    '- "primary_query": The best {min_words}-{max_words} word Pexels search query that visually '
    "and concretely illustrates the segment. Be specific and literal — never abstract.\n"
    '- "fallback_queries": An array of exactly 2 alternative queries (broader or from a different visual angle). '
    "Each should still be relevant but use different keywords.\n"
    '- "visual_mood": One of ["energetic", "calm", "dramatic", "professional", "playful", "dark", "warm", "cold"]\n'
    '- "key_text": A short impactful text to display on screen (key stat, dollar amount, surprising fact), '
    "or null if the segment has no standout moment worth highlighting visually. "
    "Only set this for ~20-30% of segments — the most striking facts, numbers, or claims.\n\n"
    "Rules:\n"
    "- Queries must describe concrete, filmable scenes — not concepts or emotions.\n"
    "- ALWAYS include people in your queries whenever possible (soldiers, workers, crowds, faces, men, women). "
    "Scenes with visible humans are strongly preferred over landscapes or objects alone.\n"
    "- Use the full transcript to understand the overall topic so your queries are thematically coherent.\n"
    "- Avoid repeating the same query across different segments.\n"
    "- Output ONLY valid JSON, no markdown fences, no explanation."
).format(min_words=QUERY_WORD_RANGE[0], max_words=QUERY_WORD_RANGE[1])


def generate_query(segment_text: str, full_transcript: str, style: str | None = None) -> dict:
    """Given a segment and full transcript context, return structured query data."""
    style_instruction = f"\nVISUAL STYLE CONSTRAINT: {style}\nAll queries must match this style — era, aesthetic, and media type." if style else ""
    prompt = (
        f"FULL TRANSCRIPT:\n{full_transcript}\n\n"
        f"---\n\n"
        f'HIGHLIGHTED SEGMENT: "{segment_text}"\n\n'
        f"{style_instruction}"
        f"Generate the JSON search query data for this segment:"
    )

    for attempt in range(MAX_RETRIES):
        try:
            response = client.models.generate_content(
                model=GEMINI_QUERY_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                ),
            )
            raw = response.text.strip()
            break
        except (APIError, httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadError, ConnectionError, TimeoutError) as e:
            print(f"[query_generator] Error (attempt {attempt + 1}/{MAX_RETRIES}): {type(e).__name__}: {e}")
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                print(f"[query_generator] Retrying in {delay}s...")
                time.sleep(delay)
            else:
                # Retries exhausted — return a safe fallback
                words = segment_text.split()[:4]
                fallback_query = " ".join(words)
                print(f"[query_generator] Using fallback query: '{fallback_query}'")
                return {
                    "primary_query": fallback_query,
                    "fallback_queries": [" ".join(words[:2])],
                    "visual_mood": "calm",
                }
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Fallback: use first few words of the segment as the query
        print(f"[query_generator] Warning: could not parse JSON, using segment text as query")
        words = segment_text.split()[:4]
        data = {
            "primary_query": " ".join(words),
            "fallback_queries": [" ".join(words[:2])],
            "visual_mood": "calm",
        }

    primary = data.get("primary_query", "").strip().strip('"').strip("'") if isinstance(data.get("primary_query"), str) else ""
    raw_fallbacks = data.get("fallback_queries", [])
    fallbacks = [q.strip().strip('"').strip("'") for q in raw_fallbacks if isinstance(q, str) and q.strip()]
    mood = data.get("visual_mood", "calm")

    # Validate: if primary is empty, fall back to segment text
    if not primary:
        words = segment_text.split()[:4]
        primary = " ".join(words)
        print(f"[query_generator] Empty primary_query, using fallback: '{primary}'")

    key_text = data.get("key_text") if isinstance(data.get("key_text"), str) and data.get("key_text", "").strip() else None

    print(f"[query_generator] '{segment_text[:60]}' → primary: '{primary}' | fallbacks: {fallbacks} | mood: {mood}" + (f" | key_text: '{key_text}'" if key_text else ""))
    return {"primary_query": primary, "fallback_queries": fallbacks, "visual_mood": mood, "key_text": key_text}


def generate_queries(segments: list[dict], style: str | None = None, on_segment_done=None) -> list[dict]:
    """Add query data to each segment dict: 'query', 'fallback_queries', 'visual_mood'.
    Skips segments that already have a 'query' key (resume support).
    Calls on_segment_done(segments) after each successful generation for incremental saving.
    """
    full_transcript = " ".join(seg["text"] for seg in segments)

    for i, seg in enumerate(segments):
        if seg.get("query"):
            continue
        if i > 0:
            time.sleep(DELAY_BETWEEN_CALLS)
        result = generate_query(seg["text"], full_transcript, style=style)
        seg["query"] = result["primary_query"]
        seg["fallback_queries"] = result["fallback_queries"]
        seg["visual_mood"] = result["visual_mood"]
        seg["key_text"] = result.get("key_text")
        if on_segment_done:
            on_segment_done(segments)

    return segments
