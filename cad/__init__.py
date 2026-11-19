"""TrainMeet CAD: the module library (#89, CAD-01–CAD-33).

A cloud service of its own with its own PostgreSQL, on TrainMeet ID (CAD-14, stacken). It uses
only contracts/, never another part's inner code (tests/test_boundaries.py). Code measures and
decides; AI only proposes (CAD-17), from part c.

Start it locally with a database:
    CAD_DATABASE_URL=postgresql:///cad CAD_MIGRATE=auto CAD_TRIAL_LOGIN=on \\
        uv run uvicorn cad.app:app --reload --port 8004
"""
