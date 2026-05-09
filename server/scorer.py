import json
import logging

from clockapp.server.config import settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a content curator for a history clock app that shows "
    "one fascinating historical fact per minute. Your job is to select the most interesting events "
    "from a Wikipedia year article and rewrite them as vivid, engaging prose for a general audience."
)

_USER_TEMPLATE = """\
Year: {year}
Wikipedia events (one per line):
{events}

Task:
1. Select the 3–5 most genuinely interesting events — things that reveal something surprising, human, \
or consequential about {year}: notable people, battles, discoveries, inventions, political upheavals, \
cultural milestones.
2. Rewrite each selected event as a single vivid sentence (max 180 chars). Make it feel alive and \
worth pausing over — not a dry citation.
3. Exclude: astronomical events, sports seasons, local administrative acts, catalog entries.

Return a JSON array only, no other text. Each element: {{"text": "<vivid sentence>", "original": "<exact Wikipedia line>"}}
If nothing is interesting enough, return: []"""


def score_events(year: int, labels: list[str]) -> list[dict]:
    """Select and rephrase the most interesting events using gpt-4o-mini.

    Returns a list of {text, original} dicts, or plain {text} dicts if LLM
    scoring is disabled. Falls back to original labels unchanged on any error.
    """
    if not settings.llm_scoring_enabled or settings.openai_api_key is None:
        return [{"text": t} for t in labels]

    if not labels:
        return []

    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _USER_TEMPLATE.format(
                        year=year,
                        events="\n".join(labels),
                    ),
                },
            ],
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or "[]"
        # LLM may return {"events": [...]} or just [...]
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            parsed = parsed.get("events", parsed.get("items", list(parsed.values())[0] if parsed else []))
        if not isinstance(parsed, list):
            raise ValueError(f"Unexpected LLM output shape: {type(parsed)}")
        result = []
        for item in parsed:
            if isinstance(item, dict) and "text" in item:
                result.append(item)
            elif isinstance(item, str):
                result.append({"text": item})
        return result[:5]
    except Exception:
        logger.warning("LLM scoring failed; returning original labels unchanged", exc_info=True)
        return [{"text": t} for t in labels]
