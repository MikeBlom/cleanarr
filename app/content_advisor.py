"""Evaluate IMDB parental guide data using a local LLM to decide
whether nudity/profanity filters should be enabled by default.

Connects to an Ollama instance (or any OpenAI-compatible local API).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)


@dataclass
class FilterRecommendation:
    """AI recommendation for whether a filter should run."""

    should_filter: bool
    reason: str  # brief explanation for the user


_CATEGORY_LABELS = {
    "FEMALE_BREAST_EXPOSED": "female breasts exposed",
    "FEMALE_GENITALIA_EXPOSED": "female genitalia exposed",
    "MALE_GENITALIA_EXPOSED": "male genitalia exposed",
    "ANUS_EXPOSED": "anus exposed",
    "BUTTOCKS_EXPOSED": "buttocks exposed",
    "GORE_BLOODSHED": "gore / bloodshed",
    "VIOLENCE_FIGHTING": "violence / fighting",
}


def _format_categories(raw: str | None) -> str:
    """Turn a comma-separated category string into a readable list."""
    if not raw:
        return "(all categories)"
    cats = [c.strip() for c in raw.split(",") if c.strip()]
    return ", ".join(_CATEGORY_LABELS.get(c, c.lower().replace("_", " ")) for c in cats)


def evaluate_nudity(
    guide: dict,
    ollama_url: str,
    ollama_model: str,
    *,
    categories: str | None = None,
) -> FilterRecommendation:
    """Decide if nudity filtering is warranted based on IMDB descriptions."""
    nudity_info = guide.get("nudity")
    if not nudity_info:
        return FilterRecommendation(
            should_filter=False,
            reason="No nudity information available from IMDB.",
        )

    severity = nudity_info.get("severity", "Unknown")
    descriptions = nudity_info.get("descriptions", [])

    if severity.lower() == "none":
        return FilterRecommendation(
            should_filter=False,
            reason="IMDB rates nudity as None.",
        )

    if not descriptions:
        return FilterRecommendation(
            should_filter=True,
            reason=f"IMDB rates nudity as {severity} but no details available; recommending filter to be safe.",
        )

    cat_list = _format_categories(categories)

    prompt = f"""The user has a video content filter that detects and blacks out specific types of on-screen nudity. Their filter is configured to detect: {cat_list}.

Below are the IMDB parental guide descriptions of the sexual/nudity content in this video. Based on these descriptions, is there actual visible nudity matching the categories above that the filter would need to black out?

IMDB Severity: {severity}

Descriptions:
{chr(10).join(f"- {d}" for d in descriptions)}

Only consider nudity that is explicitly described as visible on screen. Do NOT flag: implied scenes, sexual dialogue, kissing, swimwear, cleavage, underwear, shirtless men, or scenes that cut away before showing anything. If the descriptions only mention these things, the answer is should_filter: false.

Respond with ONLY a JSON object (no markdown, no code fences):
{{"should_filter": true/false, "reason": "brief 1-sentence explanation"}}"""

    return _query_llm(
        prompt, ollama_url, ollama_model, default_filter=True, filter_type="nudity"
    )


def evaluate_profanity(
    guide: dict,
    ollama_url: str,
    ollama_model: str,
    *,
    words: str | None = None,
    phrases: str | None = None,
) -> FilterRecommendation:
    """Decide if profanity filtering is warranted based on IMDB descriptions."""
    prof_info = guide.get("profanity")
    if not prof_info:
        return FilterRecommendation(
            should_filter=False,
            reason="No profanity information available from IMDB.",
        )

    severity = prof_info.get("severity", "Unknown")
    descriptions = prof_info.get("descriptions", [])

    if severity.lower() == "none":
        return FilterRecommendation(
            should_filter=False,
            reason="IMDB rates profanity as None.",
        )

    if not descriptions:
        return FilterRecommendation(
            should_filter=True,
            reason=f"IMDB rates profanity as {severity} but no details available; recommending filter to be safe.",
        )

    word_list = ", ".join(w.strip() for w in (words or "").splitlines() if w.strip())
    phrase_list = ", ".join(
        f'"{p.strip()}"' for p in (phrases or "").splitlines() if p.strip()
    )

    filter_desc = "The user has an audio content filter that mutes specific profanity."
    if word_list:
        filter_desc += f" Their filter is configured to mute these words: {word_list}."
    if phrase_list:
        filter_desc += f" And these phrases: {phrase_list}."
    if not word_list and not phrase_list:
        filter_desc += " It targets strong profanity (e.g. fuck, shit, bitch, damn, goddamn, slurs, and similar)."

    prompt = f"""{filter_desc}

Below are the IMDB parental guide descriptions of the profanity/language in this video. Based on these descriptions, is there profanity present that matches the words or phrases the filter is looking for?

IMDB Severity: {severity}

Descriptions:
{chr(10).join(f"- {d}" for d in descriptions)}

Only consider profanity that is explicitly mentioned in the descriptions. Do NOT flag: mild exclamations ("oh my god", "gosh", "heck"), words used in non-profane context, foreign language, or descriptions that say there is no strong profanity. If the descriptions only mention mild language, the answer is should_filter: false.

Respond with ONLY a JSON object (no markdown, no code fences):
{{"should_filter": true/false, "reason": "brief 1-sentence explanation"}}"""

    return _query_llm(
        prompt, ollama_url, ollama_model, default_filter=True, filter_type="profanity"
    )


def evaluate_violence(
    guide: dict,
    ollama_url: str,
    ollama_model: str,
    *,
    categories: str | None = None,
) -> FilterRecommendation:
    """Decide if violence/gore filtering is warranted based on IMDB descriptions."""
    violence_info = guide.get("violence")
    if not violence_info:
        return FilterRecommendation(
            should_filter=False,
            reason="No violence information available from IMDB.",
        )

    severity = violence_info.get("severity", "Unknown")
    descriptions = violence_info.get("descriptions", [])

    if severity.lower() == "none":
        return FilterRecommendation(
            should_filter=False,
            reason="IMDB rates violence as None.",
        )

    if not descriptions:
        return FilterRecommendation(
            should_filter=True,
            reason=f"IMDB rates violence as {severity} but no details available; recommending filter to be safe.",
        )

    cat_list = _format_categories(categories)

    prompt = f"""The user has a video content filter that detects and blacks out graphic violence. Their filter is configured to detect: {cat_list}.

Below are the IMDB parental guide descriptions of the violence/gore in this video. Based on these descriptions, is there graphic visual violence matching the categories above that the filter would need to black out?

IMDB Severity: {severity}

Descriptions:
{chr(10).join(f"- {d}" for d in descriptions)}

Only consider violence that is explicitly described as graphic or visually shown on screen. Do NOT flag: mild action violence, off-screen violence, verbal threats, suspenseful scenes, slapstick, or brief non-graphic fights. If the descriptions only mention mild or implied violence, the answer is should_filter: false.

Respond with ONLY a JSON object (no markdown, no code fences):
{{"should_filter": true/false, "reason": "brief 1-sentence explanation"}}"""

    return _query_llm(
        prompt, ollama_url, ollama_model, default_filter=True, filter_type="violence"
    )


def _query_llm(
    prompt: str,
    ollama_url: str,
    ollama_model: str,
    *,
    default_filter: bool,
    filter_type: str,
) -> FilterRecommendation:
    """Send prompt to local LLM and parse the response."""
    try:
        resp = httpx.post(
            f"{ollama_url.rstrip('/')}/api/generate",
            json={
                "model": ollama_model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.1},
            },
            timeout=60,
        )
        resp.raise_for_status()
        result_text = resp.json().get("response", "").strip()
        log.info("LLM raw response for %s: %s", filter_type, result_text[:500])
    except Exception:
        log.exception("Failed to query local LLM for %s evaluation", filter_type)
        return FilterRecommendation(
            should_filter=default_filter,
            reason=f"Could not reach AI advisor; defaulting to {filter_type} filter enabled.",
        )

    try:
        # Strip markdown fences if the model wraps its response
        cleaned = result_text
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[: cleaned.rfind("```")]
        cleaned = cleaned.strip()

        # Extract the first valid JSON object — LLMs often add trailing junk
        start = cleaned.find("{")
        if start != -1:
            cleaned = cleaned[start:]
        # Try parsing, progressively stripping trailing garbage
        parsed = None
        for i in range(len(cleaned), 0, -1):
            if cleaned[i - 1] == "}":
                try:
                    parsed = json.loads(cleaned[:i])
                    break
                except json.JSONDecodeError:
                    continue
        if parsed is None:
            raise json.JSONDecodeError("No valid JSON found", cleaned, 0)
        should_filter = bool(parsed.get("should_filter", default_filter))
        reason = str(parsed.get("reason", ""))
        if not reason:
            reason = (
                "AI analysis complete."
                if not should_filter
                else "AI recommends filtering."
            )

        # Sanity check: if the LLM said "don't filter" but the reason
        # clearly describes filterable content, override to filter.
        # Local LLMs sometimes return contradictory should_filter vs reason.
        if not should_filter and reason:
            reason_lower = reason.lower()
            _contradicts = False
            if filter_type == "nudity":
                _contradicts = any(
                    w in reason_lower
                    for w in (
                        "explicit",
                        "exposed",
                        "full nudity",
                        "full frontal",
                        "genitalia",
                        "breasts are shown",
                        "buttocks",
                    )
                )
            elif filter_type == "profanity":
                _contradicts = any(
                    w in reason_lower
                    for w in (
                        "explicit",
                        "frequent",
                        "strong profanity",
                        "fuck",
                        "shit",
                        "f-word",
                        "s-word",
                    )
                )
            elif filter_type == "violence":
                _contradicts = any(
                    w in reason_lower
                    for w in (
                        "graphic",
                        "gore",
                        "bloodshed",
                        "brutal",
                        "dismember",
                        "torture",
                        "gory",
                        "bloody",
                    )
                )
            if _contradicts:
                log.warning(
                    "LLM returned should_filter=false for %s but reason "
                    "suggests otherwise; overriding to true. Reason: %s",
                    filter_type,
                    reason,
                )
                should_filter = True

        return FilterRecommendation(should_filter=should_filter, reason=reason)
    except (json.JSONDecodeError, KeyError, TypeError):
        log.warning(
            "Could not parse LLM response for %s: %s", filter_type, result_text[:200]
        )
        return FilterRecommendation(
            should_filter=default_filter,
            reason=f"AI response unclear; defaulting to {filter_type} filter enabled.",
        )
