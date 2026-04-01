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


def evaluate_nudity(
    guide: dict,
    ollama_url: str,
    ollama_model: str,
) -> FilterRecommendation:
    """Decide if nudity filtering is warranted based on IMDB descriptions.

    We only care about actual exposed nudity matching our detection categories:
    female breast exposed, female genitalia exposed, male genitalia exposed,
    anus exposed, buttocks exposed.

    If the LLM can't make a determination or input is insufficient, we lean
    towards recommending filtering (safe default).
    """
    nudity_info = guide.get("nudity")
    if not nudity_info:
        return FilterRecommendation(
            should_filter=False,
            reason="No nudity information available from IMDB.",
        )

    severity = nudity_info.get("severity", "Unknown")
    descriptions = nudity_info.get("descriptions", [])

    # IMDB says None — no nudity, no need for the LLM
    if severity.lower() == "none":
        return FilterRecommendation(
            should_filter=False,
            reason="IMDB rates nudity as None.",
        )

    if not descriptions:
        # Has a severity rating but no descriptions — insufficient info, lean safe
        return FilterRecommendation(
            should_filter=True,
            reason=f"IMDB rates nudity as {severity} but no details available; recommending filter to be safe.",
        )

    prompt = f"""You are a content filter advisor. Based ONLY on the IMDB parental guide descriptions below, determine if there is actual exposed nudity that a video filter would need to black out.

We ONLY filter for these specific types of on-screen visual nudity:
- Female breasts exposed (not cleavage)
- Female genitalia exposed
- Male genitalia exposed
- Anus exposed
- Buttocks exposed

We do NOT filter for any of the following — these are NOT nudity:
- Sexual dialogue, innuendo, or verbal references
- Kissing, hugging, or romantic scenes
- Characters in swimwear, underwear, or revealing clothing
- Implied sex (under covers, scene cuts away, nothing shown)
- Cleavage or partial nudity that does not fully expose the above body parts
- Shirtless men
- Non-sexual body exposure (e.g. medical, breastfeeding)

IMPORTANT: Only report nudity that is EXPLICITLY described in the text below. Do NOT infer or assume nudity that is not clearly stated. If the descriptions only mention kissing, romance, dialogue, or implied scenes, the answer is should_filter: false.

IMDB Severity: {severity}

IMDB Descriptions:
{chr(10).join(f"- {d}" for d in descriptions)}

Respond with ONLY a JSON object (no markdown, no code fences):
{{"should_filter": true/false, "reason": "brief 1-sentence explanation"}}"""

    return _query_llm(prompt, ollama_url, ollama_model, default_filter=True, filter_type="nudity")


def evaluate_profanity(
    guide: dict,
    ollama_url: str,
    ollama_model: str,
) -> FilterRecommendation:
    """Decide if profanity filtering is warranted based on IMDB descriptions.

    If IMDB says no profanity, or the profanity is mild/not the type we filter,
    we recommend skipping the filter. If insufficient info, lean towards filtering.
    """
    prof_info = guide.get("profanity")
    if not prof_info:
        return FilterRecommendation(
            should_filter=False,
            reason="No profanity information available from IMDB.",
        )

    severity = prof_info.get("severity", "Unknown")
    descriptions = prof_info.get("descriptions", [])

    # IMDB says None — no profanity, no need for the LLM
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

    prompt = f"""You are a content filter advisor. Based ONLY on the IMDB parental guide descriptions below, determine if there is profanity present that would need audio filtering.

We filter for strong profanity including: fuck, shit, ass, asshole, bitch, bastard, damn, goddamn, cunt, cock, dick, pussy, whore, slut, racial slurs, and similar strong language.

We do NOT need to filter for:
- Mild exclamations like "oh my god", "gosh", "heck", "darn"
- Words used in non-profane context
- Foreign language that isn't recognizable as English profanity
- Descriptions that say there is NO profanity or only mild language

IMPORTANT: Only report profanity that is EXPLICITLY mentioned in the text below. Do NOT infer or assume profanity that is not clearly stated.

IMDB Severity: {severity}

IMDB Descriptions:
{chr(10).join(f"- {d}" for d in descriptions)}

Respond with ONLY a JSON object (no markdown, no code fences):
{{"should_filter": true/false, "reason": "brief 1-sentence explanation"}}"""

    return _query_llm(prompt, ollama_url, ollama_model, default_filter=True, filter_type="profanity")


def evaluate_violence(
    guide: dict,
    ollama_url: str,
    ollama_model: str,
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

    prompt = f"""You are a content filter advisor. Based ONLY on the IMDB parental guide descriptions below, determine if there is graphic violence, gore, or bloodshed that a video filter should black out.

We ONLY filter for these specific types of on-screen visual content:
- Graphic gore or bloodshed (visible blood, wounds, dismemberment)
- Intense physical violence (brutal beatings, stabbings, shootings with visible impact)
- Torture scenes with graphic detail
- Graphic war violence

We do NOT filter for:
- Mild action violence (punches, chases, comic-book style fighting)
- Off-screen violence or implied violence
- Verbal threats or intimidation
- Suspenseful or tense scenes without graphic content
- Slapstick or cartoon violence
- Brief, non-graphic fight scenes

IMPORTANT: Only report violence that is EXPLICITLY described as graphic or gory in the text below. Do NOT infer or assume graphic content that is not clearly stated.

IMDB Severity: {severity}

IMDB Descriptions:
{chr(10).join(f"- {d}" for d in descriptions)}

Respond with ONLY a JSON object (no markdown, no code fences):
{{"should_filter": true/false, "reason": "brief 1-sentence explanation"}}"""

    return _query_llm(prompt, ollama_url, ollama_model, default_filter=True, filter_type="violence")


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
            reason = "AI analysis complete." if not should_filter else "AI recommends filtering."

        # Sanity check: if the LLM said "don't filter" but the reason
        # clearly describes filterable content, override to filter.
        # Local LLMs sometimes return contradictory should_filter vs reason.
        if not should_filter and reason:
            reason_lower = reason.lower()
            _contradicts = False
            if filter_type == "nudity":
                _contradicts = any(w in reason_lower for w in (
                    "explicit", "exposed", "full nudity", "full frontal",
                    "genitalia", "breasts are shown", "buttocks",
                ))
            elif filter_type == "profanity":
                _contradicts = any(w in reason_lower for w in (
                    "explicit", "frequent", "strong profanity",
                    "fuck", "shit", "f-word", "s-word",
                ))
            elif filter_type == "violence":
                _contradicts = any(w in reason_lower for w in (
                    "graphic", "gore", "bloodshed", "brutal",
                    "dismember", "torture", "gory", "bloody",
                ))
            if _contradicts:
                log.warning(
                    "LLM returned should_filter=false for %s but reason "
                    "suggests otherwise; overriding to true. Reason: %s",
                    filter_type, reason,
                )
                should_filter = True

        return FilterRecommendation(should_filter=should_filter, reason=reason)
    except (json.JSONDecodeError, KeyError, TypeError):
        log.warning("Could not parse LLM response for %s: %s", filter_type, result_text[:200])
        return FilterRecommendation(
            should_filter=default_filter,
            reason=f"AI response unclear; defaulting to {filter_type} filter enabled.",
        )
