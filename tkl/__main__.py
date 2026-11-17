"""Start TKL on the station's computer: `uv run python -m tkl`, then open http://localhost:8090.

TKL_DATA_DIR says where the station is kept (default ~/.trainmeet-tkl), TKL_PORT which port it
answers on. Screens and tablets on the same network open the computer's address.
"""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "tkl.app:from_environment",
        factory=True,
        host=os.environ.get("TKL_HOST", "0.0.0.0"),
        port=int(os.environ.get("TKL_PORT", "8090")),
        proxy_headers=True,
    )


if __name__ == "__main__":
    main()
