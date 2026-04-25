import json
import anthropic

from ..signals.base import Contact, EmailOutput

# Prompt caching: the system prompt is sent with cache_control so it is stored
# server-side and not re-tokenized on every call — saves latency + cost.
SYSTEM_PROMPT = """You are an expert B2B sales copywriter for a HubSpot sales representative. \
Write short, highly personalized cold outreach emails.

Non-negotiable rules:
1. Never use em dashes (—)
2. Email body must be 75 words or fewer
3. Write at a 5th-grade reading level
4. Sound like a real human, not a corporate marketing team
5. Never open with "I hope this email finds you well" or any filler phrase
6. Make the email feel relevant to this specific person's role and company
7. If custom context or notes are provided, weave them in naturally
8. One clear CTA: ask for a 15-minute call
9. Subject line: 8 words or fewer, curiosity-driven, zero clickbait

Return ONLY a valid JSON object — no markdown fences, no extra text:
{"subject": "...", "body": "..."}"""


class EmailGenerator:
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def generate(self, contact: Contact, sender_name: str = "") -> EmailOutput:
        user_content = self._build_prompt(contact, sender_name)

        response = self._client.messages.create(
            model=self._model,
            max_tokens=512,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_content}],
        )

        raw = response.content[0].text.strip()
        # Strip accidental markdown fences
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1].lstrip("json").strip() if len(parts) >= 2 else raw

        parsed = json.loads(raw)
        return EmailOutput(
            subject=parsed["subject"],
            body=parsed["body"],
            contact=contact,
        )

    @staticmethod
    def _build_prompt(contact: Contact, sender_name: str) -> str:
        m = contact.metadata
        lines = [
            "Write a cold email for this prospect.\n",
            f"Name: {contact.first_name} {contact.last_name}",
            f"Title: {contact.title or 'unknown'}",
            f"Company: {contact.company_name}",
        ]
        if m.get("industry"):
            lines.append(f"Industry: {m['industry']}")
        if m.get("employee_count"):
            lines.append(f"Company size: {m['employee_count']} employees")
        if contact.company_domain:
            lines.append(f"Website: {contact.company_domain}")
        # Free-text context/notes column — highest-value personalization signal
        if m.get("context"):
            lines.append(f"\nPersonalization note: {m['context']}")
        lines.append(f"\nSender: {sender_name or 'a HubSpot sales rep'}")
        return "\n".join(lines)
