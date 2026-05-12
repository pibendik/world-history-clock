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
# 1. Bump version in pyproject.toml
# 2. Build and publish:
cd cli/
source ../../venv/bin/activate   # or whichever venv has hatch installed
rm -rf dist/
hatch build
HATCH_INDEX_USER=__token__ HATCH_INDEX_AUTH="$(awk '/password/{print $3}' ~/.pypirc)" hatch publish
```

PyPI rejects duplicate versions — always bump `version` in `pyproject.toml` first.
Token lives in `~/.pypirc` (and `~/.config/hatch/config.toml`). Rotate at
[pypi.org/manage/account/token/](https://pypi.org/manage/account/token/) if compromised.

## License

GPL-3.0-only — see [LICENSE](LICENSE).
