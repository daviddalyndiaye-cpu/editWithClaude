"""Step 1: audio -> projects/<slug>/words.json (word-level timestamps via WhisperX)."""
import json, os, sys
import truststore; truststore.inject_into_ssl()


def transcribe(audio: str, slug: str) -> str:
    out_dir = os.path.join("projects", slug)
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "words.json")
    if os.path.exists(out):
        print(f"[transcribe] cached: {out}")
        return out
    import torch, whisperx
    device = "cuda" if torch.cuda.is_available() else "cpu"
    ctype = "float16" if device == "cuda" else "int8"
    print(f"[transcribe] WhisperX on {device}...")
    model = whisperx.load_model("base", device=device, compute_type=ctype)
    a = whisperx.load_audio(audio)
    res = model.transcribe(a, batch_size=16)
    am, meta = whisperx.load_align_model(language_code=res["language"], device=device)
    res = whisperx.align(res["segments"], am, meta, a, device, return_char_alignments=False)
    words = [{"w": w["word"].strip(), "s": round(w["start"], 2), "e": round(w["end"], 2)}
             for seg in res["segments"] for w in seg.get("words", []) if "start" in w and "end" in w]
    json.dump({"audio": os.path.abspath(audio), "duration": words[-1]["e"], "words": words},
              open(out, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"[transcribe] {len(words)} words -> {out}")
    return out


if __name__ == "__main__":
    transcribe(sys.argv[1], sys.argv[2])
