import logging

from clockapp.server.config import settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a content curator for a history clock that shows one interesting historical fact "
    "per minute. Your job is to select only the most interesting and human-relevant events from a list."
)

_USER_TEMPLATE = """\
Year: {year}
Events (one per line):
{events}

Return ONLY the lines that would genuinely interest a curious general audience — things like notable people, battles, discoveries, inventions, political events, cultural milestones. \
Exclude: astronomical events (eclipses, transits), sports seasons, local administrative events, abstract concepts, technical catalog entries.
Return each kept item on its own line, exactly as written. Return nothing else. If none are interesting enough, return an empty response."""


def score_events(year: int, labels: list[str]) -> list[str]:
    """Score event labels for interestingness using gpt-4o-mini.

    Returns the filtered list of interesting labels, or the original list unchanged
    if LLM scoring is disabled or unavailable.
    """
    if not settings.llm_scoring_enabled or settings.openai_api_key is None:
        return labels

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
        )
        raw = response.choices[0].message.content or ""
        return [line.strip() for line in raw.splitlines() if line.strip()]
    except Exception:
        logger.warning("LLM scoring failed; returning original labels unchanged", exc_info=True)
        return labels
