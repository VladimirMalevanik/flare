"""Verify additive 0006 -> 0007 on disposable PostgreSQL, for either provider.

Uses the Block 4 fixture to preserve Notes, jobs, insights and generation data.
Accepts --pg-bin and --provider, like check_flares_migration.py.
"""
from check_flares_migration import main

if __name__ == '__main__':
    main(verify_analysis_runs=True)
