"""TrainMeet Catalog: the inventory of the rolling stock one has (C14, C15).

Its own service with its own PostgreSQL database (C16, CAT-30). It uses only contracts/,
never the Hub's inner code (CAT-34), and never calls the Hub (K7, CAT-37).

Start it locally with a database:
    CATALOG_DATABASE_URL=postgresql:///catalog CATALOG_MIGRATE=auto CATALOG_TRIAL_LOGIN=on \\
        uv run uvicorn catalog.app:app --reload --port 8001
"""
