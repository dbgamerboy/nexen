"""Identity, hard-coded: JARVIS = MARVIN.

The assistant is MARVIN. "JARVIS" in older notes, prompts, chats, file names and datasets is the same assistant under
its earlier name (owner decision 20260926-jarvis-is-marvin). V4 never treats them as two things:

- ``normalize`` rewrites every standalone JARVIS to MARVIN in anything V4 stores, prompts or prints.
- ``agent_key`` maps the agent name "jarvis" (and spellings of it) to "marvin" everywhere an agent is chosen.
- Names of THIRD-PARTY projects and legacy file or route names are protected and left alone, because rewriting them
  would corrupt provenance and licenses (OpenJarvis, isair/jarvis, ethanplusai/jarvis, Jarvis-v13, JARVIS-AI-Assistant,
  jarvis_runtime.py, /jarvis). Those are proper nouns, not the assistant.
"""
import re

NAME = "MARVIN"
OLD_NAME = "JARVIS"
ALIASES = {"jarvis", "j.a.r.v.i.s", "j.a.r.v.i.s.", "jarvis-ai", "jarvis ai"}
IDENTITY_STATEMENT = "JARVIS is MARVIN. MARVIN is the one NEXEN assistant; JARVIS is only its earlier name."

_PROTECT = re.compile(r"(?i)(open[-_ ]?jarvis|isair[/\\_]+jarvis|ethanplusai[/\\_]+jarvis|jarvis[-_]v\d+|jarvis[-_]ai[-_]assistant|jarvis[-_]personal[-_]ai|"
                      r"jarvis_runtime(?:\.py)?|jarvis_[a-z0-9_]+\.py|/jarvis\b|\\jarvis\b|jarvis\.(?:exe|spec|py)|Arnav3241|rajkishorbgp|just a rather very intelligent system|"
                      r"personal[- ]?jarvis|jarvis[-_]home|jarvis[-_]mcp|jarvis_memory)")
_WORD = re.compile(r"(?<![\w/\\-])(?:J\.A\.R\.V\.I\.S\.?|JARVIS|Jarvis|jarvis)(?![\w/\\-])")


def normalize(text):
    """Replace the assistant's old name with MARVIN, leaving protected third-party and legacy names untouched."""
    if not isinstance(text, str) or "arvis" not in text.lower() and "j.a.r.v.i.s" not in text.lower():
        return text
    spans = [m.span() for m in _PROTECT.finditer(text)]

    def inside(i):
        return any(a <= i < b for a, b in spans)
    out, last = [], 0
    for m in _WORD.finditer(text):
        if inside(m.start()):
            continue
        out.append(text[last:m.start()])
        word = m.group(0)
        out.append(NAME if word.isupper() or word.upper().startswith("J.") else (NAME.capitalize() if word[0].isupper() else NAME.lower()))
        last = m.end()
    out.append(text[last:])
    return "".join(out)


def agent_key(name):
    """'jarvis' and its spellings are the agent 'marvin'."""
    key = (name or "marvin").strip().lower()
    return "marvin" if key in ALIASES or key.replace(" ", "") in {a.replace(" ", "") for a in ALIASES} else key


def is_alias(name):
    return agent_key(name) == "marvin" and (name or "").strip().lower() != "marvin"
