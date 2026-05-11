# historieklokka

A history clock for the terminal. Military time **HH:MM** becomes a historical year, with a curated fact from that year — fetched live from [historieklokka.no](https://historieklokka.no).

**15:23** → year **1523** → *"Luther publishes 'On Secular Authority', laying the groundwork for separation of church and state."*

## Install

```bash
pip install historieklokka
```

## Usage

```bash
historieklokka                                     # uses historieklokka.no
historieklokka --api http://localhost:8421/api/v1  # against a local instance
```

Press `Ctrl+C` to exit.

## What it shows

- Current time as a year (e.g. 16:45 → 1645)
- The historical era that year belongs to
- A Wikipedia-sourced fact from that year, rewritten as vivid prose by an LLM
- Future years (after the current year) show curated speculative events

## Publishing to PyPI

```bash
# One-time setup
pip install hatch

# Build
cd cli/
hatch build              # creates dist/historieklokka-*.whl and .tar.gz

# Publish (requires PyPI account + API token at https://pypi.org/manage/account/token/)
hatch publish            # prompts for username (__token__) and token
```

Set `HATCH_INDEX_USER=__token__` and `HATCH_INDEX_AUTH=pypi-...` as environment variables
to skip the prompts.

## License

GPL-3.0-only — see [LICENSE](LICENSE).
