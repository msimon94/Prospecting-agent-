import httpx

from ..signals.base import EmailOutput


class SlackNotifier:
    def __init__(self, webhook_url: str):
        self._webhook_url = webhook_url

    async def notify_list(self, email_output: EmailOutput, gmail_message_id: str) -> None:
        contact = email_output.contact

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "Prospecting email sent",
                },
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*To:*\n{contact.first_name} {contact.last_name}",
                    },
                    {"type": "mrkdwn", "text": f"*Title:*\n{contact.title or 'N/A'}"},
                    {"type": "mrkdwn", "text": f"*Company:*\n{contact.company_name}"},
                    {"type": "mrkdwn", "text": f"*Email:*\n{contact.email}"},
                ],
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Subject:* {email_output.subject}",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"```{email_output.body}```",
                },
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"Gmail ID: {gmail_message_id}",
                    }
                ],
            },
        ]

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(self._webhook_url, json={"blocks": blocks})
            resp.raise_for_status()
