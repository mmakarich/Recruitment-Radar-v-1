# Recruitment Radar

Pipeline monitorujący publikacje konkurencji na 5 polskich portalach pracy:
**justjoin.it**, **nofluffjobs.com**, **rocketjobs.pl**, **theprotocol.it**, **pracuj.pl**.

System odpowiada na pytanie: czy oferta publikowana przez nas dla klienta jest
też publikowana przez innych vendorów — i jeśli tak, na jakich warunkach
(stawka, lokalizacja, tryb pracy).

## Architektura

- **Scrapery (5 portali)** → uruchamiane przez GitHub Actions (cron + workflow_dispatch).
  Snapshoty Parquet w `data/snapshots/` (Git LFS).
- **Streamlit UI** → hostowane na Streamlit Community Cloud, Google OAuth dla zespołu.
- **JD Parser** → Claude API parsuje wklejone ogłoszenie do JSON.
- **Dedup + matching** → `rapidfuzz`: deduplikacja między portalami, scoring vs nasza oferta.

## Struktura repo

```
recruitment-radar/
├── .github/workflows/      # CI + scraping cron
├── src/
│   ├── config.py           # pydantic-settings
│   ├── scrapers/           # 5 scraperów + BaseScraper
│   ├── parser/             # JD parser (Claude API)
│   ├── matching/           # dedup + compare + pipeline
│   ├── export/             # Excel + DOCX
│   └── ui/                 # Streamlit
├── tests/
│   ├── unit/               # pytest, mocki przez respx
│   ├── integration/        # @pytest.mark.live (prawdziwe API)
│   └── e2e/                # @pytest.mark.e2e (Selenium)
├── data/snapshots/         # Parquet via Git LFS
├── docker/                 # Dockerfile dla Actions
└── .streamlit/             # config + secrets template
```

## Setup lokalny

```bash
# 1. Klon i utworzenie venv
git clone <repo>
cd recruitment-radar
python3.11 -m venv .venv
source .venv/bin/activate

# 2. Instalacja zależności
pip install -e ".[dev]"
playwright install --with-deps chromium

# 3. Konfiguracja secrets
cp .env.example .env
# Wypełnij ANTHROPIC_API_KEY i pozostałe pola

# 4. Testy
pytest -v                     # unit + lint
pytest -m live -v             # testy uderzające w prawdziwe API (wymagają .env)
ruff check src tests          # lint
ruff format src tests         # auto-format
mypy src                      # type-check
```

## Uruchomienie UI lokalnie

```bash
streamlit run src/ui/app.py
```

Otwiera się na <http://localhost:8501>.

## Jak działa automatyczne odświeżanie

- Cron uruchamia się co poniedziałek o 6:00 UTC (GitHub Actions).
- Ręcznie: Actions → "Weekly scraping" → Run workflow.
- Wyniki commitowane jako snapshot Parquet do `data/snapshots/{YYYY-MM-DD}/`.

## Decyzje dotyczące bibliotek

Przed napisaniem własnej implementacji sprawdzaliśmy PyPI/GitHub. Wybrane pakiety:

| Pakiet | Wersja | Uzasadnienie |
| --- | --- | --- |
| `httpx` | ≥0.27 | Async-first HTTP client, drop-in dla requests, sync+async w jednym API |
| `tenacity` | ≥8.5 | Sprawdzony retry z exponential backoff. Lepiej niż własna pętla |
| `playwright` | ≥1.45 | Szybszy i bardziej niezawodny od Selenium. Async-native |
| `playwright-stealth` | ≥1.0.6 | Anti-bot fingerprint masking dla pracuj.pl (Prompt 5) |
| `rapidfuzz` | ≥3.9 | C++ implementacja fuzzy matching, ~10x szybsza od `thefuzz` |
| `pydantic` + `pydantic-settings` | ≥2.7 | Walidacja typów, ładowanie configu z env |
| `loguru` | ≥0.7 | Structured logging, prostsze API niż stdlib `logging` |
| `pyarrow` | ≥16.0 | Wymagany przez pandas do Parquet I/O |
| `respx` | ≥0.21 | Mock dla httpx — idiomatyczne testy scraperów bez prawdziwych requestów |
| `anthropic` | ≥0.34 | Oficjalny SDK Claude API (Prompt 7) |
| `python-docx` | ≥1.1 | Aktywnie utrzymywany, generowanie DOCX raportów (Prompt 8) |
| `openpyxl` | ≥3.1 | Standard dla Excel w Pythonie, conditional formatting + hyperlinks |
| `PyGithub` | ≥2.3 | Wywołanie `workflow_dispatch` z UI (Prompt 9, 11) |

Wszystkie pakiety mają licencje MIT/Apache 2.0/BSD i aktywne maintenance (commit < 12 miesięcy).

## Konwencje

- **Python 3.11+** z type hints. `mypy --strict`.
- **Formatowanie:** `ruff format` (line length 100). Lint: `ruff check`.
- **Testy:** pytest, pokrycie min. 80% dla logiki, 90% dla `matching/`.
- **Daty:** zawsze `datetime` z `UTC`.
- **Stawki:** `SalaryRange(min, max, currency, period, contract)`.
- **Snapshoty:** Parquet w `data/snapshots/YYYY-MM-DD/<portal>.parquet`.

## Workflow Git

- Każdy prompt = jeden feature branch (`feat/<skrót-promptu>`).
- Conventional Commits (`feat:`, `fix:`, `test:`, `docs:`, `chore:`).
- PR opisuje co robi, link do prompta, checklistę akceptacji.
- Merge dopiero po zielonym CI + review.

## Status promptów

Patrz checklist na końcu `Recruitment_Radar_Prompty.docx`.

## Jak działa automatyczne odświeżanie danych

Recruitment Radar ma workflow GitHub Actions `Weekly scraping`, który uruchamia scrapery i zapisuje wyniki jako snapshoty Parquet w `data/snapshots/{YYYY-MM-DD}/`.

### Harmonogram

Workflow uruchamia się automatycznie co poniedziałek o 6:00 UTC:

```text
0 6 * * 1
```

### Uruchomienie ręczne

Workflow można uruchomić ręcznie z GitHub UI:

```text
Actions → Weekly scraping → Run workflow
```

Dostępne parametry:

- `keywords` — lista fraz po przecinku, np. `python,javascript,react`
- `portals` — lista portali po przecinku albo `all`
- `limit_per_portal` — maksymalna liczba ofert na portal

### Wyniki

Każde uruchomienie zapisuje:

```text
data/snapshots/{YYYY-MM-DD}/{portal}.parquet
data/snapshots/{YYYY-MM-DD}/summary.json
```

`summary.json` zawiera:

- liczbę ofert per portal,
- czas wykonania per portal,
- błędy per portal,
- łączną liczbę ofert.

Jeśli jeden scraper zakończy się błędem, pozostałe scrapery nadal działają. Workflow zwróci exit code `1`, żeby GitHub Actions oznaczył problem, ale zapisze dane z portali, które zakończyły się sukcesem.

### Lokalny smoke run

```bash
python scripts/run_scraping.py --keywords "python" --portals "justjoin,nofluff" --limit-per-portal 10
```
