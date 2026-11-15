"""The mails ID's API sends: invitations to a club or a shared fleet (KONTO-29, KONTO-35), and
Hjälp och fel to Beahead's support (KONTO-06, ID9).

The same mail server as Keycloak's codes (#66): Scaleway's Transactional Email in the test
environment, with the password from ID's vault. The address is never written to the log.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from contracts.id import ProblemCode
from id.roles import Refused
from id.settings import Smtp

LOGGER = logging.getLogger("id.mail")


def invitation_text(title: str, sender: str, link: str) -> tuple[str, str]:
    subject = f"{sender} bjuder in dig: {title}"
    body = (
        f"{sender} har bjudit in dig i TrainMeet: {title}.\n\n"
        f"Logga in i TrainMeet ID med den här adressen och svara ja eller nej:\n{link}\n\n"
        "Inbjudan ger ingenting förrän du har svarat ja. Känner du inte igen den kan du "
        "strunta i det här mejlet.\n\nTrainMeet ID\n"
    )
    return subject, body


class SmtpMailer:
    def __init__(self, smtp: Smtp | None) -> None:
        self.smtp = smtp

    def invitation(self, to: str, title: str, sender: str, link: str) -> None:
        if self.smtp is None:
            raise Refused(503, ProblemCode.UNAVAILABLE, "ID kan inte skicka mejl här.")
        subject, body = invitation_text(title, sender, link)
        message = EmailMessage()
        message["From"] = f"TrainMeet <{self.smtp.sender}>"
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        try:
            self._send(message)
        except (OSError, smtplib.SMTPException) as error:
            LOGGER.warning("Inbjudan gick inte att skicka: %s", type(error).__name__)
            raise Refused(
                503,
                ProblemCode.UNAVAILABLE,
                "Inbjudan gick inte att skicka. Försök igen om en stund.",
            ) from error

    def help(self, to: str, reply_to: str, subject: str, body: str) -> None:
        """Hjälp och fel to support (KONTO-06). Answers go to the person's verified address."""
        if self.smtp is None:
            raise Refused(503, ProblemCode.UNAVAILABLE, "ID kan inte skicka mejl här.")
        message = EmailMessage()
        message["From"] = f"TrainMeet <{self.smtp.sender}>"
        message["To"] = to
        message["Reply-To"] = reply_to
        message["Subject"] = subject
        message.set_content(body)
        try:
            self._send(message)
        except (OSError, smtplib.SMTPException) as error:
            LOGGER.warning("Hjälp och fel gick inte att skicka: %s", type(error).__name__)
            raise Refused(
                503,
                ProblemCode.UNAVAILABLE,
                "Det gick inte att skicka. Försök igen om en stund.",
            ) from error

    def _send(self, message: EmailMessage) -> None:
        smtp = self.smtp
        assert smtp is not None
        context = ssl.create_default_context()
        server: smtplib.SMTP
        if smtp.ssl:
            server = smtplib.SMTP_SSL(smtp.host, smtp.port, timeout=15, context=context)
        else:
            server = smtplib.SMTP(smtp.host, smtp.port, timeout=15)
        with server:
            if smtp.starttls:
                server.starttls(context=context)
            if smtp.auth:
                server.login(smtp.user, smtp.password())
            server.send_message(message)
