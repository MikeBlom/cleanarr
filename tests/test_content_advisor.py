from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.content_advisor import (
    evaluate_nudity,
    evaluate_profanity,
    evaluate_violence,
)


def _mock_llm_response(json_str):
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"response": json_str}
    return resp


def test_evaluate_nudity_no_info():
    result = evaluate_nudity({}, "http://ollama", "model")
    assert result.should_filter is False
    assert "No nudity information" in result.reason


def test_evaluate_nudity_severity_none():
    guide = {"nudity": {"severity": "None", "descriptions": []}}
    result = evaluate_nudity(guide, "http://ollama", "model")
    assert result.should_filter is False


def test_evaluate_nudity_no_descriptions():
    guide = {"nudity": {"severity": "Moderate", "descriptions": []}}
    result = evaluate_nudity(guide, "http://ollama", "model")
    assert result.should_filter is True
    assert "no details available" in result.reason


@patch("app.content_advisor.httpx.post")
def test_evaluate_nudity_llm_says_filter(mock_post):
    mock_post.return_value = _mock_llm_response(
        '{"should_filter": true, "reason": "Explicit nudity described"}'
    )
    guide = {"nudity": {"severity": "Severe", "descriptions": ["Full frontal nudity"]}}
    result = evaluate_nudity(guide, "http://ollama", "model")
    assert result.should_filter is True


@patch("app.content_advisor.httpx.post")
def test_evaluate_nudity_llm_says_no_filter(mock_post):
    mock_post.return_value = _mock_llm_response(
        '{"should_filter": false, "reason": "Only kissing scenes described"}'
    )
    guide = {"nudity": {"severity": "Mild", "descriptions": ["Kissing only"]}}
    result = evaluate_nudity(guide, "http://ollama", "model")
    assert result.should_filter is False


@patch("app.content_advisor.httpx.post")
def test_evaluate_nudity_llm_timeout(mock_post):
    mock_post.side_effect = Exception("Connection timeout")
    guide = {"nudity": {"severity": "Moderate", "descriptions": ["Some content"]}}
    result = evaluate_nudity(guide, "http://ollama", "model")
    assert result.should_filter is True  # safe default
    assert "Could not reach" in result.reason


def test_evaluate_profanity_severity_none():
    guide = {"profanity": {"severity": "None", "descriptions": []}}
    result = evaluate_profanity(guide, "http://ollama", "model")
    assert result.should_filter is False


@patch("app.content_advisor.httpx.post")
def test_evaluate_profanity_with_descriptions(mock_post):
    mock_post.return_value = _mock_llm_response(
        '{"should_filter": true, "reason": "Contains frequent f-words"}'
    )
    guide = {
        "profanity": {
            "severity": "Severe",
            "descriptions": ["Uses the f-word frequently"],
        }
    }
    result = evaluate_profanity(guide, "http://ollama", "model")
    assert result.should_filter is True


def test_evaluate_violence_no_info():
    result = evaluate_violence({}, "http://ollama", "model")
    assert result.should_filter is False


@patch("app.content_advisor.httpx.post")
def test_evaluate_violence_llm_response(mock_post):
    mock_post.return_value = _mock_llm_response(
        '{"should_filter": true, "reason": "Graphic gore described"}'
    )
    guide = {"violence": {"severity": "Severe", "descriptions": ["Graphic gore"]}}
    result = evaluate_violence(guide, "http://ollama", "model")
    assert result.should_filter is True


@patch("app.content_advisor.httpx.post")
def test_query_llm_strips_markdown_fences(mock_post):
    mock_post.return_value = _mock_llm_response(
        '```json\n{"should_filter": false, "reason": "Mild content"}\n```'
    )
    guide = {"nudity": {"severity": "Mild", "descriptions": ["Mild"]}}
    result = evaluate_nudity(guide, "http://ollama", "model")
    assert result.should_filter is False


@patch("app.content_advisor.httpx.post")
def test_query_llm_invalid_json(mock_post):
    mock_post.return_value = _mock_llm_response("this is not json at all")
    guide = {"nudity": {"severity": "Mild", "descriptions": ["Content"]}}
    result = evaluate_nudity(guide, "http://ollama", "model")
    assert result.should_filter is True  # defaults to safe
    assert "unclear" in result.reason.lower() or "default" in result.reason.lower()


@patch("app.content_advisor.httpx.post")
def test_contradiction_override(mock_post):
    mock_post.return_value = _mock_llm_response(
        '{"should_filter": false, "reason": "Exposed breasts are shown briefly"}'
    )
    guide = {"nudity": {"severity": "Moderate", "descriptions": ["Brief nudity"]}}
    result = evaluate_nudity(guide, "http://ollama", "model")
    assert result.should_filter is True  # overridden due to contradiction
