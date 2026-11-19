"""How CAD says no: a status, a code and a Swedish message (contracts.cad.CadProblem)."""

from __future__ import annotations

from contracts.cad import ProblemCode


class Refused(Exception):
    """CAD says no. app.py turns it into a CadProblem with the status."""

    def __init__(self, status: int, code: ProblemCode, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def not_found() -> Refused:
    return Refused(404, ProblemCode.NOT_FOUND, "Modulen finns inte, eller så ser du den inte.")


def forbidden() -> Refused:
    return Refused(
        403, ProblemCode.FORBIDDEN, "Bara ägaren och de med rollen redigera ändrar modulen."
    )


def invalid(message: str) -> Refused:
    return Refused(422, ProblemCode.INVALID, message)


def login() -> Refused:
    return Refused(401, ProblemCode.LOGIN, "Logga in först.")


def unavailable() -> Refused:
    return Refused(503, ProblemCode.UNAVAILABLE, "TrainMeet ID svarar inte just nu. Försök igen.")
