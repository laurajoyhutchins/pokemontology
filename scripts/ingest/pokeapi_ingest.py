#!/usr/bin/env python3
"""Compatibility wrapper for pokemontology.ingest.pokeapi_ingest."""

from pokemontology.ingest.pokeapi_ingest import *  # noqa: F403
from pokemontology.ingest.pokeapi_ingest import main


if __name__ == "__main__":
    main()
