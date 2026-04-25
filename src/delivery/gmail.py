import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


class GmailClient:
    def __init__(
        self,
        credentials_file: str = "credentials/gmail_credentials.json",
        token_file: str = "credentials/gmail_token.json",
    ):
        self._credentials_file = credentials_file
        self._token_file = token_file
        self._service = None

    def authorize(self) -> None:
        """Run the OAuth flow. Call this once to create the token file."""
        flow = InstalledAppFlow.from_client_secrets_file(self._credentials_file, SCOPES)
        creds = flow.run_local_server(port=0)
        Path(self._token_file).parent.mkdir(parents=True, exist_ok=True)
        with open(self._token_file, "w") as f:
            f.write(creds.to_json())
        print(f"Token saved to {self._token_file}")

    def _get_service(self):
        if self._service:
            return self._service

        creds: Optional[Credentials] = None
        if Path(self._token_file).exists():
            creds = Credentials.from_authorized_user_file(self._token_file, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with open(self._token_file, "w") as f:
                    f.write(creds.to_json())
            else:
                raise RuntimeError(
                    f"No valid Gmail token found at {self._token_file}. "
                    "Run `python main.py auth` first."
                )

        self._service = build("gmail", "v1", credentials=creds)
        return self._service

    def send(self, to: str, subject: str, body: str) -> str:
        """Send a plain-text email. Returns the Gmail message ID."""
        msg = MIMEMultipart("alternative")
        msg["to"] = to
        msg["subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        result = (
            self._get_service()
            .users()
            .messages()
            .send(userId="me", body={"raw": raw})
            .execute()
        )
        return result["id"]
