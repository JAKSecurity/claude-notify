#!/usr/bin/env python3
"""Generate TTS audio from a briefing markdown file using Edge TTS.

Usage:
    python scripts/generate_tts.py data/briefings/2026-03-14.md
    python scripts/generate_tts.py data/briefings/2026-03-14.md --output briefing.mp3
    python scripts/generate_tts.py data/briefings/2026-03-14.md --voice en-US-GuyNeural

Requires:
    pip install edge-tts

Output: MP3 file saved alongside the briefing (or to --output path)
"""

import argparse
import asyncio
import re
import sys
from pathlib import Path

try:
    import edge_tts
except ImportError:
    print("Error: edge-tts not installed. Run: pip install edge-tts", file=sys.stderr)
    sys.exit(1)


def markdown_to_speech_text(md_text):
    """Convert markdown to clean speech text."""
    text = md_text

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

    # Clean up whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    return text


def preprocess_for_speech(text):
    """Expand abbreviations and symbols into speech-friendly text."""
    # Temperature: "70 F" or "70°F" -> "70 degrees"
    text = re.sub(r"(\d+)\s*°?\s*F\b", r"\1 degrees", text)

    # Speed: "15 mph" -> "15 miles per hour"
    text = re.sub(r"(\d+)\s*mph\b", r"\1 miles per hour", text, flags=re.IGNORECASE)

    # Percent: "50%" -> "50 percent"
    text = re.sub(r"(\d+)\s*%", r"\1 percent", text)

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


async def generate_audio(text, output_path, voice="en-US-AndrewMultilingualNeural"):
    """Generate MP3 from text using Edge TTS."""
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(output_path))


def main():
    parser = argparse.ArgumentParser(description="Generate TTS audio from briefing")
    parser.add_argument("input", help="Path to briefing markdown file")
    parser.add_argument("--output", "-o", help="Output MP3 path (default: same dir as input)")
    parser.add_argument("--voice", "-v", default="en-US-AndrewMultilingualNeural",
                        help="Edge TTS voice (default: en-US-AndrewMultilingualNeural)")
    args = parser.parse_args()

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

    print(f"Generating audio ({len(speech_text)} chars, voice: {args.voice})...")
    asyncio.run(generate_audio(speech_text, output_path, args.voice))
    print(f"Audio saved: {output_path}")


if __name__ == "__main__":
    main()
