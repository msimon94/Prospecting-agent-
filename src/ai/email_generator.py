import json
import anthropic

from ..signals.base import EnrichedContact, EmailOutput, SignalType

# Prompt caching: this system prompt is sent with cache_control so it's stored
# server-side and not re-tokenized on every call.
SYSTEM_PROMPT = """You are an expert B2B sales copywriter for a HubSpot sales representative. \
Write short, highly personalized cold outreach emails.

Non-negotiable rules:
1. Never use em dashes (—)
2. Email body must be 75 words or fewer
3. Write at a 5th-grade reading level
4. Sound like a real human, not a corporate marketing team
5. Never open with "I hope this email finds you well" or any equivalent filler
6. Reference the specific intent signal — make it feel timely and relevant
7. One clear CTA: ask for a 15-minute call
8. Subject line: 8 words or fewer, curiosity-driven, zero clickbait

Return ONLY a valid JSON object — no markdown fences, no prose:
{"subject": "...", "body": "..."}"""

_SIGNAL_CONTEXT: dict = {
    SignalType.JOB_CHANGE: (
        "This person recently started a new role. "
        "New leaders typically evaluate and replace tools in their first 90 days."
    ),
    SignalType.FUNDING_ROUND: (
        "This company just raised a funding round. "
        "They are actively investing in new tools and scaling their go-to-market."
    ),
    SignalType.TECH_INSTALL: (
        "This company recently installed a competitor or complementary technology, "
        "signaling active investment in this space."
    ),
    SignalType.TECH_UNINSTALL: (
        "This company recently removed a competitor technology. "
        "They may be in the market for an alternative."
    ),
    SignalType.HIRING_SURGE: (
        "This company is on an aggressive hiring spree in relevant departments, "
        "signaling rapid growth and new budget."
    ),
    SignalType.G2_INTENT: (
        "This company has been actively researching this product category on G2, "
        "showing strong, near-term buying intent."
    ),
}


class EmailGenerator:
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def generate(self, enriched: EnrichedContact, sender_name: str = "") -> EmailOutput:
        contact = enriched.contact
        signal = enriched.signal

        linkedin_snippet = ""
        if enriched.linkedin_data:
            summary = (enriched.linkedin_data.get("summary") or "")[:200]
            if summary:
                linkedin_snippet = f"\nLinkedIn summary: {summary}"

        signal_details = self._format_signal_details(signal)
        signal_context = _SIGNAL_CONTEXT.get(signal.signal_type, "")

        user_content = (
            f"Write a cold email for this prospect.\n\n"
            f"Contact:\n"
            f"  Name: {contact.first_name} {contact.last_name}\n"
            f"  Title: {contact.title}\n"
            f"  Company: {contact.company_name}\n"
            f"  Industry: {contact.metadata.get('industry') or 'unknown'}\n"
            f"  Company size: {contact.metadata.get('employee_count') or 'unknown'} employees"
            f"{linkedin_snippet}\n\n"
            f"Intent signal: {signal.signal_type.value.replace('_', ' ')}\n"
            f"Why it matters: {signal_context}\n"
            f"Signal details: {signal_details}\n\n"
            f"Sender: {sender_name or 'a HubSpot sales rep'}"
        )

        response = self._client.messages.create(
            model=self._model,
            max_tokens=512,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    # Prompt caching — avoids re-tokenizing the 300-token system
                    # prompt on every call, cutting latency and cost.
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_content}],
        )

        raw = response.content[0].text.strip()
        # Strip accidental markdown fences Claude occasionally adds
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1].lstrip("json").strip() if len(parts) >= 2 else raw

        parsed = json.loads(raw)
        return EmailOutput(
            subject=parsed["subject"],
            body=parsed["body"],
            contact=contact,
            signal=signal,
        )

    @staticmethod
    def _format_signal_details(signal) -> str:
        m = signal.metadata
        parts = []
        if signal.signal_type == SignalType.FUNDING_ROUND:
            amount = m.get("funding_amount") or 0
            stage = m.get("funding_stage") or ""
            parts.append(f"Raised ${amount:,} ({stage})")
            if m.get("funding_date"):
                parts.append(f"Date: {m['funding_date']}")
        elif signal.signal_type == SignalType.JOB_CHANGE:
            if m.get("title"):
                parts.append(f"New title: {m['title']}")
            if m.get("job_start_date"):
                parts.append(f"Start date: {m['job_start_date']}")
        elif signal.signal_type == SignalType.HIRING_SURGE:
            parts.append(f"{m.get('open_positions', 0)} open positions")
            if m.get("departments"):
                parts.append(f"Depts: {', '.join(m['departments'])}")
        elif signal.signal_type in (SignalType.TECH_INSTALL, SignalType.TECH_UNINSTALL):
            techs = [t for t in (m.get("technologies") or []) if t]
            if techs:
                parts.append(f"Technologies: {', '.join(techs[:3])}")
        return "; ".join(parts) if parts else "see signal metadata"
