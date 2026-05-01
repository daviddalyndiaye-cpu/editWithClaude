import json
import re
import time
import httpx
from google import genai
from google.genai import types
from google.genai.errors import APIError
from config import GEMINI_API_KEY, GEMINI_TRANSCRIPTION_MODEL, GEMINI_QUERY_MODEL, MIN_SEGMENT_DURATION, MAX_SEGMENT_DURATION

MAX_RETRIES = 3
RETRY_BASE_DELAY = 10  # seconds — transcription is expensive, give more time

client = genai.Client(api_key=GEMINI_API_KEY)


def transcribe(audio_path: str) -> list[dict]:
    """
    Upload an audio file to Gemini and return timestamped segments.
    Each segment: {"text": str, "start_sec": float, "end_sec": float}
    """
    print(f"[transcriber] Uploading audio: {audio_path}")
    audio_file = None
    for attempt in range(MAX_RETRIES):
        try:
            audio_file = client.files.upload(file=audio_path)
            break
        except (APIError, httpx.RemoteProtocolError, httpx.ConnectError,
                httpx.ReadError, ConnectionError, TimeoutError) as e:
            print(f"[transcriber] Upload error (attempt {attempt + 1}/{MAX_RETRIES}): {type(e).__name__}: {e}")
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                print(f"[transcriber] Retrying in {delay}s...")
                time.sleep(delay)
            else:
                raise RuntimeError(f"Audio upload failed after {MAX_RETRIES} attempts") from e

    # Wait for the file to be processed
    while audio_file.state.name == "PROCESSING":
        time.sleep(2)
        audio_file = client.files.get(name=audio_file.name)

    if audio_file.state.name == "FAILED":
        raise RuntimeError("Gemini file processing failed.")

    prompt = """Transcribe this audio file sentence by sentence.
Return ONLY a valid JSON array with no extra text or markdown.
Each element must have:
  "text": the sentence text,
  "start_sec": start time in seconds (float),
  "end_sec": end time in seconds (float)

Example:
[
  {"text": "Welcome to our channel.", "start_sec": 0.0, "end_sec": 2.5},
  {"text": "Today we talk about AI.", "start_sec": 2.5, "end_sec": 5.1}
]"""

    print("[transcriber] Requesting transcription from Gemini...")
    response = None
    for attempt in range(MAX_RETRIES):
        try:
            response = client.models.generate_content(
                model=GEMINI_TRANSCRIPTION_MODEL,
                contents=[prompt, audio_file],
            )
            break
        except (APIError, httpx.RemoteProtocolError, httpx.ConnectError,
                httpx.ReadError, ConnectionError, TimeoutError) as e:
            print(f"[transcriber] Error (attempt {attempt + 1}/{MAX_RETRIES}): {type(e).__name__}: {e}")
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                print(f"[transcriber] Retrying in {delay}s...")
                time.sleep(delay)
            else:
                raise RuntimeError(f"Transcription failed after {MAX_RETRIES} attempts") from e

    raw = response.text.strip()
    # Strip markdown code fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        sentences = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[transcriber] Failed to parse Gemini response as JSON: {e}")
        print(f"[transcriber] Raw response:\n{raw[:500]}")
        raise RuntimeError("Gemini returned invalid JSON for transcription.") from e

    # Validate structure
    for i, s in enumerate(sentences):
        if not all(k in s for k in ("text", "start_sec", "end_sec")):
            raise RuntimeError(f"Sentence {i} missing required keys: {s}")

    print(f"[transcriber] Got {len(sentences)} sentences.")

    segments = _merge_sentences(sentences)
    print(f"[transcriber] Merged into {len(segments)} segments.")
    return segments


def transcribe_and_segment(audio_path: str, style: str | None = None) -> list[dict]:
    """
    Single Gemini pass: transcribe audio AND group into narrative blocks.
    Each block covers one visual idea and includes query + mood directly.
    Returns segments with: text, start_sec, end_sec, query, fallback_queries, visual_mood, key_text
    Falls back to transcribe() + generate_queries() if Gemini returns bad data.
    """
    print(f"[transcriber] Uploading audio for narrative segmentation: {audio_path}")
    audio_file = None
    for attempt in range(MAX_RETRIES):
        try:
            audio_file = client.files.upload(file=audio_path)
            break
        except (APIError, httpx.RemoteProtocolError, httpx.ConnectError,
                httpx.ReadError, ConnectionError, TimeoutError) as e:
            print(f"[transcriber] Upload error (attempt {attempt + 1}/{MAX_RETRIES}): {type(e).__name__}: {e}")
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                print(f"[transcriber] Retrying in {delay}s...")
                time.sleep(delay)
            else:
                raise RuntimeError(f"Audio upload failed after {MAX_RETRIES} attempts") from e

    while audio_file.state.name == "PROCESSING":
        time.sleep(2)
        audio_file = client.files.get(name=audio_file.name)

    if audio_file.state.name == "FAILED":
        raise RuntimeError("Gemini file processing failed.")

    style_instruction = (
        f"\nVISUAL STYLE: {style}\nAll queries must match this style — era, aesthetic, and media type."
        if style else ""
    )

    system_instruction = (
        "You are a professional documentary video editor. "
        "You will receive an audio voiceover. Your job is to:\n"
        "1. Transcribe the audio accurately with timestamps\n"
        "2. Group the transcript into narrative blocks — each block covers ONE visual idea or topic\n"
        "3. For each block, generate a specific image/footage search query\n\n"
        "Rules for grouping:\n"
        "- A block should last between 8 and 20 seconds\n"
        "- Group consecutive sentences that describe the same visual scene or topic\n"
        "- Never split a single idea across two blocks\n"
        "- Aim for 30-50 blocks per 4-5 minute video (more blocks = more visual variety)\n\n"
        "Rules for queries:\n"
        "- Queries must describe concrete, filmable scenes — not concepts or emotions\n"
        "- ALWAYS include people whenever possible (soldiers, workers, crowds, faces)\n"
        "- Be specific and literal — never abstract\n"
        f"{style_instruction}\n\n"
        "Return ONLY a valid JSON array, no markdown fences, no explanation.\n"
        "Each element must have exactly these keys:\n"
        '  "text": full transcript text of this block,\n'
        '  "start_sec": start time in seconds (float),\n'
        '  "end_sec": end time in seconds (float),\n'
        '  "query": best 3-6 word search query for this block,\n'
        '  "fallback_queries": array of 2 alternative queries,\n'
        '  "visual_mood": one of ["energetic","calm","dramatic","professional","playful","dark","warm","cold"],\n'
        '  "key_text": short impactful on-screen text (stat, fact, amount) or null\n'
    )

    prompt = "Transcribe and segment this audio into narrative visual blocks as instructed."

    print("[transcriber] Requesting narrative segmentation from Gemini...")
    response = None
    for attempt in range(MAX_RETRIES):
        try:
            response = client.models.generate_content(
                model=GEMINI_QUERY_MODEL,
                contents=[prompt, audio_file],
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                ),
            )
            break
        except (APIError, httpx.RemoteProtocolError, httpx.ConnectError,
                httpx.ReadError, ConnectionError, TimeoutError) as e:
            print(f"[transcriber] Error (attempt {attempt + 1}/{MAX_RETRIES}): {type(e).__name__}: {e}")
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                print(f"[transcriber] Retrying in {delay}s...")
                time.sleep(delay)
            else:
                raise RuntimeError(f"Narrative segmentation failed after {MAX_RETRIES} attempts") from e

    raw = response.text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        segments = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[transcriber] Narrative JSON parse failed: {e} — will use fallback pipeline")
        return []

    # Validate structure
    required = {"text", "start_sec", "end_sec", "query", "fallback_queries", "visual_mood"}
    valid = []
    for i, seg in enumerate(segments):
        if not required.issubset(seg.keys()):
            print(f"[transcriber] Block {i} missing keys, skipping: {seg}")
            continue
        if seg["end_sec"] <= seg["start_sec"]:
            print(f"[transcriber] Block {i} has invalid timestamps, skipping")
            continue
        # Normalize key_text
        seg["key_text"] = seg.get("key_text") if isinstance(seg.get("key_text"), str) and seg.get("key_text", "").strip() else None
        valid.append(seg)

    if len(valid) < 3:
        print(f"[transcriber] Too few valid blocks ({len(valid)}) — will use fallback pipeline")
        return []

    print(f"[transcriber] Narrative segmentation: {len(valid)} blocks "
          f"({valid[0]['start_sec']:.1f}s → {valid[-1]['end_sec']:.1f}s)")
    for seg in valid:
        duration = seg["end_sec"] - seg["start_sec"]
        print(f"  [{seg['start_sec']:.1f}s-{seg['end_sec']:.1f}s] ({duration:.1f}s) → '{seg['query']}'")

    return valid


def _merge_sentences(sentences: list[dict]) -> list[dict]:
    """
    Merge adjacent sentences so each segment is between MIN and MAX duration.
    Then split any segment that still exceeds MAX duration.
    """
    merged = []
    current = None

    for s in sentences:
        if current is None:
            current = dict(s)
            continue

        current_duration = current["end_sec"] - current["start_sec"]
        combined_duration = s["end_sec"] - current["start_sec"]

        if current_duration < MIN_SEGMENT_DURATION:
            current["text"] += " " + s["text"]
            current["end_sec"] = s["end_sec"]
        elif combined_duration <= MAX_SEGMENT_DURATION:
            current["text"] += " " + s["text"]
            current["end_sec"] = s["end_sec"]
        else:
            merged.append(current)
            current = dict(s)

    if current:
        merged.append(current)

    # Split segments that exceed MAX duration into equal chunks
    segments = []
    for seg in merged:
        duration = seg["end_sec"] - seg["start_sec"]
        if duration <= MAX_SEGMENT_DURATION:
            segments.append(seg)
        else:
            num_chunks = max(2, round(duration / MAX_SEGMENT_DURATION))
            chunk_dur = duration / num_chunks
            words = seg["text"].split()
            words_per_chunk = max(1, len(words) // num_chunks)
            for c in range(num_chunks):
                start = seg["start_sec"] + c * chunk_dur
                end = seg["start_sec"] + (c + 1) * chunk_dur
                # Distribute words roughly evenly
                w_start = c * words_per_chunk
                w_end = (c + 1) * words_per_chunk if c < num_chunks - 1 else len(words)
                text = " ".join(words[w_start:w_end]) or seg["text"]
                segments.append({"text": text, "start_sec": round(start, 3), "end_sec": round(end, 3)})
            print(f"[transcriber] Split {duration:.1f}s segment into {num_chunks} chunks of ~{chunk_dur:.1f}s")

    return segments


# ---------------------------------------------------------------------------
# WhisperX pipeline — word-level timestamps + Gemini narrative grouping
# ---------------------------------------------------------------------------

def transcribe_whisperx(audio_path: str, style: str | None = None) -> list[dict]:
    """
    WhisperX → phrase chunks → Gemini groups by phrase index → resolve timestamps from WhisperX.

    Gemini never touches timestamps — it only returns first/last phrase indices per block.
    Timestamps are resolved deterministically from WhisperX word data.
    Falls back to [] on any error so caller can use Gemini pipeline.
    """
    try:
        import whisperx
        import torch
    except ImportError:
        print("[whisperx] whisperx not installed — skipping")
        return []

    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    print(f"[whisperx] Loading model on {device} ({compute_type})...")

    try:
        model = whisperx.load_model("base", device=device, compute_type=compute_type)
        audio = whisperx.load_audio(audio_path)

        print("[whisperx] Transcribing with word-level alignment...")
        result = model.transcribe(audio, batch_size=16)

        align_model, metadata = whisperx.load_align_model(
            language_code=result["language"], device=device
        )
        result = whisperx.align(
            result["segments"], align_model, metadata, audio, device,
            return_char_alignments=False
        )
    except Exception as e:
        print(f"[whisperx] Transcription failed: {e} — falling back to Gemini")
        return []

    # Collect word-level data
    words = []
    for seg in result["segments"]:
        for w in seg.get("words", []):
            if "start" in w and "end" in w and "word" in w:
                words.append({
                    "word": w["word"].strip(),
                    "start": round(w["start"], 3),
                    "end": round(w["end"], 3),
                })

    if not words:
        print("[whisperx] No word-level data — falling back to Gemini")
        return []

    total_duration = words[-1]["end"]
    print(f"[whisperx] Got {len(words)} words spanning {total_duration:.1f}s")

    speech_rate = _compute_speech_rate(words, total_duration)

    # Group words into phrases of ~10 words — Gemini works on phrase indices, not timestamps
    phrases = _words_to_phrases(words, target_words=10)
    print(f"[whisperx] Grouped into {len(phrases)} phrases for Gemini")

    # Build compact phrase list: "42: [45.20s-48.10s] Brooklyn Bridge was completed in 1883"
    phrase_list = "\n".join(
        f"{i}: [{p['start']:.2f}s-{p['end']:.2f}s] {p['text']}"
        for i, p in enumerate(phrases)
    )

    style_instruction = (
        f"\nVISUAL STYLE: {style}\nAll queries must match this style."
        if style else ""
    )

    system_instruction = (
        "You are a documentary video editor. You receive numbered phrases with timestamps.\n"
        "Group consecutive phrases into narrative blocks — each block covers ONE visual scene or topic.\n\n"
        "STRICT RULES:\n"
        "- MAXIMUM block duration: 15 seconds. If a topic spans 30s, split it into 2 blocks of 15s.\n"
        "- MINIMUM block duration: 5 seconds (at least 2-3 phrases per block).\n"
        "- Target: 1 block every 10-15 seconds. A 13-minute audio should produce 50-80 blocks.\n"
        "- Each block = ONE visual shot. Think like a film editor: cut often, vary the angle.\n"
        "- CALL-TO-ACTION passages ('like', 'subscribe', 'abonne-toi', 'mets un like', 'comment') → "
        "assign query 'subscribe call to action' and mood 'energetic'. Do NOT skip them.\n"
        "- Never merge two different visual scenes into one block.\n"
        f"{style_instruction}\n\n"
        "Return ONLY a valid JSON array. Each element:\n"
        '  "first_phrase": index of first phrase in this block (integer),\n'
        '  "last_phrase": index of last phrase in this block (integer),\n'
        '  "query": best 3-6 word search query describing the VISUAL content (not the concept),\n'
        '  "fallback_queries": array of 2 alternative queries,\n'
        '  "visual_mood": one of ["energetic","calm","dramatic","professional","playful","dark","warm","cold"],\n'
        '  "key_text": short impactful on-screen text (stat, name, date) or null\n'
        "\nDo NOT include timestamps — only phrase indices. Blocks must be contiguous and cover ALL phrases."
    )

    prompt = (
        f"PHRASES ({len(phrases)} total, audio spans {phrases[-1]['end']:.0f}s):\n{phrase_list}\n\n"
        f"Target: ~{max(10, int(phrases[-1]['end'] / 12))} blocks total. "
        "Group into narrative visual blocks — MAXIMUM 15 seconds each."
    )

    print("[whisperx] Asking Gemini to group phrases into narrative blocks...")
    response = None
    for attempt in range(MAX_RETRIES):
        try:
            response = client.models.generate_content(
                model=GEMINI_QUERY_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                ),
            )
            break
        except (APIError, httpx.RemoteProtocolError, httpx.ConnectError,
                httpx.ReadError, ConnectionError, TimeoutError) as e:
            print(f"[whisperx] Gemini error (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BASE_DELAY * (2 ** attempt))
            else:
                print("[whisperx] Gemini grouping failed — falling back")
                return []

    raw = response.text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        blocks = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[whisperx] JSON parse failed: {e} — falling back")
        return []

    # Resolve timestamps from WhisperX data — Gemini only gave us phrase indices
    required = {"first_phrase", "last_phrase", "query", "fallback_queries", "visual_mood"}
    valid = []
    for i, block in enumerate(blocks):
        if not required.issubset(block.keys()):
            print(f"[whisperx] Block {i} missing keys — skipping")
            continue

        first = int(block["first_phrase"])
        last = int(block["last_phrase"])

        if first < 0 or last >= len(phrases) or first > last:
            print(f"[whisperx] Block {i} has invalid phrase range [{first}-{last}] — skipping")
            continue

        # Timestamps come directly from WhisperX — Gemini never touched them
        start_sec = phrases[first]["start"]
        end_sec = phrases[last]["end"]

        if end_sec <= start_sec:
            continue

        text = " ".join(p["text"] for p in phrases[first: last + 1])
        wps = _avg_speech_rate(speech_rate, start_sec, end_sec)

        valid.append({
            "text": text,
            "start_sec": start_sec,
            "end_sec": end_sec,
            "query": block["query"],
            "fallback_queries": block.get("fallback_queries", []),
            "visual_mood": block.get("visual_mood", "calm"),
            "key_text": (
                block.get("key_text")
                if isinstance(block.get("key_text"), str) and block.get("key_text", "").strip()
                else None
            ),
            "words_per_sec": wps,
        })

    if len(valid) < 3:
        print(f"[whisperx] Too few valid blocks ({len(valid)}) — falling back")
        return []

    # Force-split any block that exceeds MAX_BLOCK_SEC — Gemini sometimes ignores the rule
    MAX_BLOCK_SEC = 20.0
    split_valid = []
    for seg in valid:
        dur = seg["end_sec"] - seg["start_sec"]
        if dur <= MAX_BLOCK_SEC:
            split_valid.append(seg)
            continue
        n = max(2, round(dur / 12.0))  # target ~12s per sub-block
        chunk_dur = dur / n
        print(f"[whisperx] Force-splitting {dur:.1f}s block '{seg['query']}' into {n} sub-blocks")
        for k in range(n):
            sub_start = seg["start_sec"] + k * chunk_dur
            sub_end = seg["start_sec"] + (k + 1) * chunk_dur
            split_valid.append({
                **seg,
                "start_sec": round(sub_start, 3),
                "end_sec": round(sub_end, 3),
                "words_per_sec": _avg_speech_rate(speech_rate, sub_start, sub_end),
            })
    valid = split_valid
    print(f"[whisperx] {len(valid)} blocks — timestamps resolved from WhisperX (no Gemini drift)")
    for seg in valid:
        dur = seg["end_sec"] - seg["start_sec"]
        wps = seg["words_per_sec"]
        pace = "fast" if wps > 2.5 else ("slow" if wps < 1.2 else "normal")
        print(f"  [{seg['start_sec']:.3f}s-{seg['end_sec']:.3f}s] ({dur:.1f}s, {wps:.1f}w/s {pace}) → '{seg['query']}'")

    return valid


def _words_to_phrases(words: list[dict], target_words: int = 10) -> list[dict]:
    """
    Group words into phrases of ~target_words each.
    Each phrase: {text, start, end, word_start_idx, word_end_idx}
    Breaks on natural sentence boundaries (., !, ?) when near target size.
    """
    phrases = []
    i = 0
    while i < len(words):
        chunk = []
        while i < len(words):
            chunk.append(words[i])
            i += 1
            # Break at sentence boundary once we're near target size
            if len(chunk) >= target_words and chunk[-1]["word"].rstrip().endswith((".", "!", "?")):
                break
            # Hard break at 2x target to avoid very long phrases
            if len(chunk) >= target_words * 2:
                break
        if chunk:
            phrases.append({
                "text": " ".join(w["word"] for w in chunk),
                "start": chunk[0]["start"],
                "end": chunk[-1]["end"],
            })
    return phrases


def _compute_speech_rate(words: list[dict], total_duration: float) -> list[float]:
    """
    Return a list of words/sec sampled every second across the audio.
    Index i = speech rate during second [i, i+1).
    """
    n_buckets = int(total_duration) + 1
    counts = [0] * n_buckets
    for w in words:
        bucket = int(w["start"])
        if bucket < n_buckets:
            counts[bucket] += 1
    # Smooth with a 3-second rolling average
    smoothed = []
    for i in range(n_buckets):
        window = counts[max(0, i - 1): i + 2]
        smoothed.append(sum(window) / len(window))
    return smoothed


def _avg_speech_rate(speech_rate: list[float], start: float, end: float) -> float:
    """Average words/sec over a time range using the precomputed rate table."""
    if not speech_rate or end <= start:
        return 0.0
    buckets = speech_rate[int(start): int(end) + 1]
    return sum(buckets) / len(buckets) if buckets else 0.0
