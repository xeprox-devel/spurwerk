"""Zentrale Versionsnummer — einzige Quelle für App, Build und Changelog."""

APP_NAME = "Spurwerk"
__version__ = "2.0.0"

# Eine Versionsnummer, eine Wahrheit: alle HTTP-Anfragen (Downloader, TMDb,
# Update-Prüfung) melden sich mit diesem User-Agent.
USER_AGENT = f"{APP_NAME}/{__version__}"
