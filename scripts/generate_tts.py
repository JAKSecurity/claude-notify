#!/usr/bin/env python3
"""Generate TTS audio from a briefing markdown file using Edge TTS.

Usage:
    python scripts/generate_tts.py data/briefings/2026-03-14.md
    python scripts/generate_tts.py data/briefings/2026-03-14.md --output briefing.mp3
    python scripts/generate_tts.py data/briefings/2026-03-14.md --voice en-US-GuyNeural

Requires:
    pip install edge-tts
    pip install mutagen  (optional; used for actual MP3 duration in instrumentation)

Output: MP3 file saved alongside the briefing (or to --output path)

Instrumentation ([051]):
    Every run appends a JSONL record to data/logs/tts/YYYY-MM.jsonl with input
    char/word counts, estimated duration, output file size, actual duration, and
    a truncation flag. If actual/estimated falls below TRUNCATION_RATIO_THRESHOLD
    a warning is printed to stderr. Instrumentation is additive and never blocks
    TTS generation on its own failure.
"""

import argparse
import asyncio
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

try:
    import edge_tts
except ImportError:
    print("Error: edge-tts not installed. Run: pip install edge-tts", file=sys.stderr)
    sys.exit(1)

try:
    from mutagen.mp3 import MP3 as _MutagenMP3
    _HAS_MUTAGEN = True
except ImportError:
    _HAS_MUTAGEN = False


# [051] instrumentation constants
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG_DIR = PROJECT_ROOT / "data" / "logs" / "tts"

# Empirical calibration from tts_backfill_analysis.py run over 37 archived
# briefings 2026-03-12..2026-04-23: avg 13.25 chars/sec, range 11.61..16.22.
# Threshold 0.70 catches a 30%+ shortfall without false-positive-ing the fast
# end of the speech-rate distribution.
ESTIMATED_CHARS_PER_SECOND = 13.25
TRUNCATION_RATIO_THRESHOLD = 0.70  # actual/estimated below this -> warn


def convert_tables_to_speech(text):
    """Convert markdown tables to natural spoken sentences."""
    lines = text.split("\n")
    result = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # Detect table row (starts with |)
        if line.startswith("|") and line.endswith("|"):
            # Collect all contiguous table lines
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            # Parse: skip separator rows, extract headers + data
            rows = []
            for tl in table_lines:
                if re.match(r"^\|[\s\-:|]+\|$", tl):
                    continue
                cells = [c.strip() for c in tl.split("|")[1:-1]]
                rows.append(cells)
            if len(rows) >= 2:
                headers = [h.lower().strip() for h in rows[0]]
                for data_row in rows[1:]:
                    parts = []
                    for j, cell in enumerate(data_row):
                        val = cell.strip()
                        if not val or j >= len(headers):
                            continue
                        hdr = headers[j]
                        if hdr in ("day", "date"):
                            parts.append(val)
                        elif "high" in hdr and "low" in hdr:
                            # "High/Low" header — expand "80/62" or "80 F / 62 F"
                            m = re.match(r"(\d+)\s*F?\s*/\s*(\d+)\s*F?", val)
                            if m:
                                parts.append(f"high of {m.group(1)} and low of {m.group(2)}")
                            else:
                                parts.append(f"high and low {val}")
                        elif hdr == "high":
                            parts.append(f"high of {val}")
                        elif hdr == "low":
                            parts.append(f"low of {val}")
                        elif hdr in ("conditions", "forecast", "description"):
                            parts.append(val)
                        elif hdr in ("precip", "precipitation", "rain"):
                            if val.strip() not in ("0%", "0", "--", ""):
                                parts.append(f"{val} chance of precipitation")
                        else:
                            parts.append(f"{hdr}: {val}")
                    if parts:
                        result.append(", ".join(parts) + ".")
            elif rows:
                for row in rows:
                    result.append(", ".join(c.strip() for c in row if c.strip()))
            result.append("")  # blank line after table
        else:
            result.append(lines[i])
            i += 1
    return "\n".join(result)


def markdown_to_speech_text(md_text):
    """Convert markdown to clean speech text."""
    text = md_text

    # Convert tables to natural text before stripping other formatting
    text = convert_tables_to_speech(text)

    # Remove markdown formatting
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)  # headers
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)  # bold
    text = re.sub(r"\*(.+?)\*", r"\1", text)  # italic
    text = re.sub(r"`(.+?)`", r"\1", text)  # inline code
    text = re.sub(r"^>\s+", "", text, flags=re.MULTILINE)  # blockquotes
    text = re.sub(r"^-\s+", "• ", text, flags=re.MULTILINE)  # list items
    text = re.sub(r"^\d+\.\s+", "", text, flags=re.MULTILINE)  # numbered lists
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)  # links
    text = re.sub(r"```[\s\S]*?```", "", text)  # code blocks
    text = re.sub(r"^---+\s*$", "", text, flags=re.MULTILINE)  # horizontal rules
    text = re.sub(r"\s*\|\s*", ", ", text)  # inline pipe separators

    # Clean up whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    return text


def preprocess_for_speech(text):
    """Expand abbreviations and symbols into speech-friendly text."""

    # --- [023] Strip source citations to prevent multilingual voice accent switching ---
    # Remove parenthetical source attributions like (CNN, CNBC, NPR) or (Al Jazeera)
    text = re.sub(r"\s*\((?:[A-Z][A-Za-z\s.]+(?:,\s*)?)+\)\s*$", "", text, flags=re.MULTILINE)
    # Remove standalone URLs
    text = re.sub(r"https?://\S+", "", text)
    # Remove HTML comments (status lines)
    text = re.sub(r"<!--.*?-->", "", text)
    # Remove "Generated:" footer lines
    text = re.sub(r"^\*Generated:.*\*$", "", text, flags=re.MULTILINE)

    # --- [049] Defense-in-depth against language switching. The Andrew
    # Multilingual voice language-switches on foreign cues like accented
    # letters ("Morón"), currency symbols ("€90B"), and sometimes on unusual
    # Unicode punctuation. The primary fix for [049] is swapping the default
    # voice to en-US-AndrewNeural (non-multilingual); this preprocess is the
    # second line of defense and also improves Andrew-non-multi output by
    # removing punctuation quirks that confuse prosody.
    #
    # Step 1: typographic punctuation -> ASCII equivalents.
    _PUNCT_MAP = {
        "\u2014": ", ",       # em dash — pause
        "\u2013": "-",        # en dash – hyphen
        "\u2212": "-",        # minus
        "\u2018": "'", "\u2019": "'",   # curly single quotes
        "\u201C": '"', "\u201D": '"',   # curly double quotes
        "\u2026": "...",      # horizontal ellipsis
        "\u00A0": " ",        # non-breaking space
        "\u2192": " to ",     # rightwards arrow
        "\u2190": " from ",   # leftwards arrow
        "\u2194": " between ",  # left-right arrow
    }
    for src, dst in _PUNCT_MAP.items():
        text = text.replace(src, dst)

    # Step 2: currency symbols -> spoken words. Always expand *before* stripping
    # diacritics (next step), since some currency symbols are in the same
    # Unicode block that diacritic-folding touches.
    _CURRENCY_MAP = {
        "\u20AC": " euros ",  # €
        "\u00A3": " pounds ", # £
        "\u00A5": " yen ",    # ¥
        "\u00A2": " cents ",  # ¢
    }
    for sym, word in _CURRENCY_MAP.items():
        text = text.replace(sym, word)

    # Step 3: strip variation selectors and common emoji ranges. These rarely
    # carry semantic meaning in a spoken briefing and can trigger language
    # detection.
    text = re.sub(r"[\uFE00-\uFE0F]", "", text)            # variation selectors
    text = re.sub(r"[\u2600-\u27BF]", "", text)            # misc symbols + dingbats (⚠, ⭐, ✅, etc.)
    text = re.sub(r"[\U0001F300-\U0001FAFF]", "", text)    # emoji supplementary planes

    # Step 4: accent/diacritic folding — "Morón" -> "Moron", "café" -> "cafe".
    # Preserves the English-appropriate reading while eliminating the strongest
    # multilingual trigger. Uses NFKD decomposition + strip combining marks.
    nfkd = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in nfkd if not unicodedata.combining(c))

    # Step 5: collapse any remaining non-ASCII to "?". Should be nearly no-op
    # after steps 1-4 but guards against future content additions.
    text = text.encode("ascii", errors="replace").decode("ascii").replace("?", "")

    # --- [034] Weather compact format expansions ---
    # "high/low 80/62" or "High/Low: 80/62" -> "high of 80 and low of 62"
    text = re.sub(
        r"[Hh]igh/[Ll]ow:?\s*(\d+)\s*/\s*(\d+)",
        r"high of \1 and low of \2",
        text
    )
    # Standalone temperature pairs: "80/62 F" or "80 F / 62 F"
    text = re.sub(
        r"(\d+)\s*F?\s*/\s*(\d+)\s*F\b",
        r"high of \1 and low of \2 degrees",
        text
    )
    # Date shorthand in tables: "4/13" -> "April 13"
    month_names = {
        "1": "January", "2": "February", "3": "March", "4": "April",
        "5": "May", "6": "June", "7": "July", "8": "August",
        "9": "September", "10": "October", "11": "November", "12": "December",
    }
    def expand_date_shorthand(m):
        month = month_names.get(m.group(1), m.group(1))
        return f"{month} {m.group(2)}"
    text = re.sub(r"\b(\d{1,2})/(\d{1,2})\b", expand_date_shorthand, text)

    # Temperature: "70 F" or "70°F" -> "70 degrees"
    text = re.sub(r"(\d+)\s*°?\s*F\b", r"\1 degrees", text)

    # Speed: "15 mph" -> "15 miles per hour"
    text = re.sub(r"(\d+)\s*mph\b", r"\1 miles per hour", text, flags=re.IGNORECASE)

    # Percent: "50%" -> "50 percent"
    text = re.sub(r"(\d+)\s*%", r"\1 percent", text)

    # Common abbreviations
    text = re.sub(r"\bPrecip\b", "precipitation", text, flags=re.IGNORECASE)
    text = re.sub(r"\btemp\b", "temperature", text, flags=re.IGNORECASE)
    text = re.sub(r"\bWER\b", "word error rate", text)
    text = re.sub(r"\bCVEs?\b", "security vulnerabilities", text)

    # Compass directions (longer patterns first to avoid partial matches)
    compass = {
        "NNE": "north northeast", "ENE": "east northeast",
        "ESE": "east southeast", "SSE": "south southeast",
        "SSW": "south southwest", "WSW": "west southwest",
        "WNW": "west northwest", "NNW": "north northwest",
        "NE": "northeast", "SE": "southeast",
        "SW": "southwest", "NW": "northwest",
        "N": "north", "S": "south", "E": "east", "W": "west",
    }
    for abbr, full in compass.items():
        text = re.sub(rf"\b{abbr}\b", full, text)

    return text


# [049] Default voice swapped from en-US-AndrewMultilingualNeural ->
# en-US-AndrewNeural to stop mid-readout language switching on foreign cues
# (accented chars, currency symbols). Identical voice personality/family; only
# the multilingual switching behavior is dropped. Override via:
#   python generate_tts.py briefing.md --voice en-US-AndrewMultilingualNeural
# or set tts.voice in data/config.yaml.
DEFAULT_VOICE = "en-US-AndrewNeural"


def _resolve_default_voice():
    """Pick default voice in order: env var -> config.yaml -> module default."""
    env_voice = os.environ.get("AI_ASSISTANT_TTS_VOICE")
    if env_voice:
        return env_voice
    try:
        import yaml  # deferred import; yaml may not be imported elsewhere in this script
        config_path = PROJECT_ROOT / "data" / "config.yaml"
        if config_path.exists():
            cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            tts_cfg = cfg.get("tts") or {}
            voice = tts_cfg.get("voice")
            if voice:
                return voice
    except Exception:
        pass
    return DEFAULT_VOICE


async def generate_audio(text, output_path, voice=None):
    """Generate MP3 from text using Edge TTS."""
    if voice is None:
        voice = _resolve_default_voice()
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(output_path))


# --- [051] Instrumentation helpers ---------------------------------------------

def _get_mp3_duration_seconds(mp3_path):
    """Return actual MP3 duration in seconds, or None on any failure.

    Prefers mutagen (accurate). Falls back to bitrate-based estimate from file
    size if mutagen is unavailable OR the file can't be parsed as a valid MP3
    (e.g., truncated or corrupt). Never raises — instrumentation must not
    block TTS.
    """
    # Try mutagen first for accurate duration.
    if _HAS_MUTAGEN:
        try:
            return float(_MutagenMP3(str(mp3_path)).info.length)
        except Exception:
            pass  # fall through to bitrate estimate
    # Bitrate fallback: Edge TTS defaults to 48 kbps mono -> 6000 bytes/sec.
    # Useful precisely when mutagen can't parse the file (truncated MP3s).
    try:
        size = Path(mp3_path).stat().st_size
        return size / 6000.0
    except Exception:
        return None


def _log_tts_run(record, log_dir):
    """Append a JSONL record to data/logs/tts/YYYY-MM.jsonl. Silent on failure."""
    try:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        log_path = log_dir / f"{month}.jsonl"
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass  # Instrumentation must never block TTS.


def instrument_run(*, input_path, output_path, speech_text, voice,
                   synth_start, synth_end, error=None, log_dir=None):
    """Build and emit one instrumentation record; return the record.

    The caller is responsible for handling TTS itself; this helper only
    observes. If `error` is not None the record still includes all available
    measurements so post-mortem scripts can correlate failures.
    """
    if log_dir is None:
        log_dir = DEFAULT_LOG_DIR

    input_chars = len(speech_text)
    input_words = len(speech_text.split())
    estimated_duration_sec = input_chars / ESTIMATED_CHARS_PER_SECOND if input_chars else 0.0
    synth_elapsed_sec = max(0.0, synth_end - synth_start) if synth_end else 0.0

    output_path_obj = Path(output_path) if output_path else None
    output_size_bytes = None
    actual_duration_sec = None
    if output_path_obj and output_path_obj.exists():
        try:
            output_size_bytes = output_path_obj.stat().st_size
        except Exception:
            output_size_bytes = None
        actual_duration_sec = _get_mp3_duration_seconds(output_path_obj)

    duration_ratio = None
    truncation_suspected = False
    if estimated_duration_sec and actual_duration_sec:
        duration_ratio = actual_duration_sec / estimated_duration_sec
        truncation_suspected = duration_ratio < TRUNCATION_RATIO_THRESHOLD

    record = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "input_path": str(input_path) if input_path else None,
        "output_path": str(output_path_obj) if output_path_obj else None,
        "voice": voice,
        "input_chars": input_chars,
        "input_words": input_words,
        "estimated_duration_sec": round(estimated_duration_sec, 2),
        "output_size_bytes": output_size_bytes,
        "actual_duration_sec": round(actual_duration_sec, 2) if actual_duration_sec else None,
        "duration_ratio": round(duration_ratio, 3) if duration_ratio else None,
        "truncation_suspected": truncation_suspected,
        "synth_elapsed_sec": round(synth_elapsed_sec, 2),
        "duration_source": "mutagen" if _HAS_MUTAGEN else "bitrate_estimate",
        "error": error,
    }

    _log_tts_run(record, log_dir)

    if truncation_suspected:
        expected_min = round(estimated_duration_sec / 60.0, 1)
        actual_min = round(actual_duration_sec / 60.0, 1)
        print(
            f"[TTS] WARNING: audio may be truncated — "
            f"expected ~{expected_min} min, actual {actual_min} min "
            f"(ratio {duration_ratio:.2f}). See data/logs/tts/ for details.",
            file=sys.stderr,
        )

    return record


def main():
    parser = argparse.ArgumentParser(description="Generate TTS audio from briefing")
    parser.add_argument("input", help="Path to briefing markdown file")
    parser.add_argument("--output", "-o", help="Output MP3 path (default: same dir as input)")
    parser.add_argument(
        "--voice", "-v",
        default=None,
        help=(
            "Edge TTS voice. Default resolved from "
            "$AI_ASSISTANT_TTS_VOICE -> data/config.yaml tts.voice -> "
            f"'{DEFAULT_VOICE}' (non-multilingual, set in [049] to stop "
            "mid-readout language switching)."
        ),
    )
    parser.add_argument(
        "--log-dir",
        default=None,
        help=(
            "Directory for [051] instrumentation JSONL logs. Default: "
            f"{DEFAULT_LOG_DIR}. Override here OR via $AI_ASSISTANT_TTS_LOG_DIR "
            "when running from a different repo (e.g., briefing task calls "
            "claude-notify's copy but logs should land in AI Assistant)."
        ),
    )
    args = parser.parse_args()
    if args.voice is None:
        args.voice = _resolve_default_voice()
    if args.log_dir is None:
        args.log_dir = os.environ.get("AI_ASSISTANT_TTS_LOG_DIR") or str(DEFAULT_LOG_DIR)

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: {input_path} not found", file=sys.stderr)
        sys.exit(1)

    md_text = input_path.read_text(encoding="utf-8")
    speech_text = markdown_to_speech_text(md_text)
    speech_text = preprocess_for_speech(speech_text)

    if not speech_text.strip():
        print("Error: no text to convert", file=sys.stderr)
        sys.exit(1)

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path.with_suffix(".mp3")

    estimated_min = (len(speech_text) / ESTIMATED_CHARS_PER_SECOND) / 60.0
    print(
        f"Generating audio ({len(speech_text)} chars, "
        f"~{estimated_min:.1f} min estimated, voice: {args.voice})..."
    )

    synth_start = time.monotonic()
    synth_error = None
    try:
        asyncio.run(generate_audio(speech_text, output_path, args.voice))
    except Exception as e:  # surface but still log
        synth_error = repr(e)
    synth_end = time.monotonic()

    # [051] Always instrument, success or failure.
    instrument_run(
        input_path=input_path,
        output_path=output_path,
        speech_text=speech_text,
        voice=args.voice,
        synth_start=synth_start,
        synth_end=synth_end,
        error=synth_error,
        log_dir=args.log_dir,
    )

    if synth_error:
        print(f"Error during TTS synthesis: {synth_error}", file=sys.stderr)
        sys.exit(1)

    print(f"Audio saved: {output_path}")


if __name__ == "__main__":
    main()
