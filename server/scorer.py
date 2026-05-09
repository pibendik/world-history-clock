import json
import logging
import os

from clockapp.server.config import settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT_EN = (
    "You are a content curator for Historieklokka — a history clock app that shows "
    "one fascinating historical fact per minute. Your job is to select the most interesting events "
    "from a Wikipedia year article and rewrite them as vivid, engaging prose for a general audience."
)

_SYSTEM_PROMPT_NO = """\
Du er innholdskurator for Historieklokka — en historieklokkapp som viser én fascinerende historisk \
hendelse per minutt. Oppgaven din er å velge de mest interessante hendelsene fra en Wikipedia-artikkel \
og skrive dem om til levende, engasjerende prosa på norsk bokmål.

SPRÅK OG STIL — SVÆRT VIKTIG:
Skriv på godt, levende østlandsnorsk bokmål. Teksten skal høres ut som noe en norsk forfatter ville \
ha skrevet — ikke som en oversettelse fra engelsk. Unngå konstruksjoner som like gjerne kunne stått \
i en engelsk tekst.

Unngå disse typiske oversettelsesfeilene:
- IKKE: «Dette resulterte i en dramatisk endring» → SKRIV: «Dette snudde opp ned på alt»
- IKKE: «En rekke hendelser fant sted» → SKRIV: «Det skjedde mye» / «Mye sto på spill»
- IKKE: «Som et resultat av» → SKRIV: «Og dermed» / «Slik sett» / «Det ble følgen»
- IKKE: «I løpet av dette året» → SKRIV: «Dette året» / «Da» / «Det var i dette året at»
- IKKE: «Ble drept i en konflikt» → SKRIV: «falt i kamp» / «ble hugget ned» / «mistet livet»
- IKKE: «Hadde en betydelig innvirkning på» → SKRIV: «forandret», «preget», «satte spor»
- IKKE: «krever N liv» / «tar N liv» → SKRIV: «N dør» / «N mister livet» / «N omkomne»
- IKKE: «noe som sårer samfunnet» / «noe som reiser spørsmål» → del opp i egne korte setninger
- IKKE lang avslutningsfloskel («et mørkt kapittel i nasjonens historie») tedd på slutten av en \
  allerede fullstendig setning → avslutt heller skarpt, eller gjør floskelsetningen til en selvstendig \
  påstand: «Det er et mørkt kapittel i landets historie.»

Bruk typisk norsk:
- Lange sammensatte ord der de passer: «sjøslag», «kongemord», «folkevandring», «maktkamp»
- «da» som avslutningspartikel: «Det var jo ikke tilfeldig, da.»
- «jo» som selvfølgelighetsmarkør: «Det var jo nettopp slik at…»
- «vel» som modererende partikel: «Det var vel ingen overraskelse…»
- Setningsstrukturer med verbal tidlig: «Da kongen falt, ble riket delt.»
- «man» heller enn «du» i generelle utsagn: «Man kan jo lure på…»
- Fortellerstemme, som en klok onkel som holder foredrag — engasjert, litt tørr, ikke høytidelig\
"""

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

_USER_TEMPLATE_NO = """\
År: {year}
Wikipedia-hendelser (én per linje):
{events}

Oppgave:
1. Velg de 3–5 mest genuint interessante hendelsene — ting som avslører noe overraskende, menneskelig \
eller viktig om {year}: bemerkelsesverdige personer, slag, oppdagelser, oppfinnelser, politiske \
omveltninger, kulturelle milepæler.
2. Skriv hver valgte hendelse om til én levende setning (maks 180 tegn). Gjør den engasjerende og \
verdt å stoppe opp ved — ikke tørr sitering.
3. Utelat: astronomiske hendelser, sportssesonger, lokale administrative vedtak, katalogoppføringer.

Grammatikk og idiom — unngå disse konkrete feilene:
- IKKE «brann krever 320 liv» → SKRIV «320 dør i brannen» / «320 omkomne»
- IKKE «jordskjelvet krever 3000 liv» → SKRIV «3000 mister livet» / «3000 dør»
- IKKE «et jordskjelv og tsunamien rammer» → SKRIV «Et jordskjelv og en tsunami rammer»
- IKKE «noe som sårer samfunnet og reiser spørsmål om X» → del i to setninger: «Samfunnet blir preget. \
Spørsmål om X kommer på dagsordenen.»
- IKKE lang avslutningsfloskel limt på slutten av en fullstendig setning → avslutt skarpt, eller \
lag floskelsetningen til en selvstendig påstand

Returner kun en JSON-array, ingen annen tekst. Hvert element: {{"text": "<levende setning>", "original": "<nøyaktig Wikipedia-linje>"}}
Hvis ingenting er interessant nok, returner: []"""


def score_events(year: int, labels: list[str]) -> list[dict]:
    """Select and rephrase the most interesting events using gpt-4o-mini.

    Returns a list of {text, original} dicts, or plain {text} dicts if LLM
    scoring is disabled. Falls back to original labels unchanged on any error.
    """
    if not settings.llm_scoring_enabled or settings.openai_api_key is None:
        return [{"text": t} for t in labels]

    if not labels:
        return []

    is_norwegian = settings.lang == "no"
    system_prompt = _SYSTEM_PROMPT_NO if is_norwegian else _SYSTEM_PROMPT_EN
    user_template = _USER_TEMPLATE_NO if is_norwegian else _USER_TEMPLATE

    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": user_template.format(
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
