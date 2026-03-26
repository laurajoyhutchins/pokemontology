#!/usr/bin/env python3
"""Compatibility wrapper for pokemontology.ingest.pokeapi_scrape."""

from pokemontology.ingest.pokeapi_scrape import *  # noqa: F403
from pokemontology.ingest.pokeapi_scrape import main


if __name__ == "__main__":
    main()
