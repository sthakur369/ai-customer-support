"""Compatibility entry point for creating/resetting the synthetic demo database.

WARNING: this script resets and repopulates the demo tables. It is not a migration
script and should not be run against real customer data.
"""
from database.ingest_data import main

if __name__ == "__main__":
    main()
