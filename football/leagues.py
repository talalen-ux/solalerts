"""The seven leagues the agent covers, keyed by short code."""

LEAGUES = {
    "EPL": {"name": "Premier League", "file": "en.1"},
    "LALIGA": {"name": "La Liga", "file": "es.1"},
    "BUNDESLIGA": {"name": "Bundesliga", "file": "de.1"},
    "SERIEA": {"name": "Serie A", "file": "it.1"},
    "LIGUE1": {"name": "Ligue 1", "file": "fr.1"},
    "EREDIVISIE": {"name": "Eredivisie", "file": "nl.1"},
    "PRIMEIRA": {"name": "Primeira Liga", "file": "pt.1"},
}


def season_label(year: int) -> str:
    """2026 -> '2026-27' (a season is named by the year it starts in)."""
    return f"{year}-{str(year + 1)[-2:]}"


def season_start_year(d) -> int:
    """European seasons start in July: 2026-11-05 belongs to 2026-27."""
    return d.year if d.month >= 7 else d.year - 1


def resolve(code: str) -> str:
    key = code.upper().replace(" ", "").replace("-", "")
    if key not in LEAGUES:
        raise SystemExit(f"Unknown league {code!r}. Choose from: {', '.join(LEAGUES)} or ALL")
    return key
