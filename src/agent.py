import asyncio
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from rich.console import Console
from rich.table import Table

from .signals.apollo import ApolloSignalMonitor
from .signals.base import CompanySignal, EmailOutput
from .orchestration.deduplicator import SignalDeduplicator
from .orchestration.router import route_signals
from .enrichment.apollo import ApolloEnrichmentClient
from .enrichment.apify import ApifyLinkedInScraper
from .enrichment.hubspot import HubSpotClient
from .ai.email_generator import EmailGenerator
from .delivery.gmail import GmailClient
from .delivery.slack import SlackNotifier

console = Console()

# Don't re-contact a domain more often than this
RECONTACT_COOLDOWN_DAYS = 30


class ProspectingAgent:
    def __init__(self, config: dict):
        self._cfg = config

        self._signal_monitor = ApolloSignalMonitor(config["apollo_api_key"])
        self._apollo_enricher = ApolloEnrichmentClient(config["apollo_api_key"])
        self._hubspot = HubSpotClient(config["hubspot_access_token"])
        self._apify = (
            ApifyLinkedInScraper(config["apify_api_token"])
            if config.get("apify_api_token")
            else None
        )
        self._email_gen = EmailGenerator(config["anthropic_api_key"])
        self._gmail = GmailClient(
            credentials_file=config.get(
                "gmail_credentials_file", "credentials/gmail_credentials.json"
            ),
            token_file=config.get(
                "gmail_token_file", "credentials/gmail_token.json"
            ),
        )
        self._slack = (
            SlackNotifier(config["slack_webhook_url"])
            if config.get("slack_webhook_url")
            else None
        )
        self._dedup = SignalDeduplicator()

    # ── Main entry point ──────────────────────────────────────────────────────

    async def run(self) -> List[dict]:
        console.rule("[bold blue]Prospecting Agent")
        console.print(f"[dim]{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}[/dim]\n")

        # Layer 1 — fetch signals
        raw_signals = await self._fetch_all_signals()
        console.print(f"[green]Fetched {len(raw_signals)} raw signals[/green]")

        # Layer 2 — deduplicate + route
        new_signals = self._dedup.filter_new(raw_signals)
        console.print(f"[green]{len(new_signals)} new after deduplication[/green]")

        if not new_signals:
            console.print("[yellow]Nothing new to process.[/yellow]")
            return []

        routed = route_signals(new_signals)
        max_emails = self._cfg.get("max_emails_per_run", 10)
        top = routed[:max_emails]
        self._print_signals_table(top)

        results = []
        for signal, score in top:
            result = await self._process_signal(signal)
            if result:
                results.append(result)

        console.rule(f"[bold green]Done — {len(results)} email(s) sent")
        return results

    # ── Signal fetching ───────────────────────────────────────────────────────

    async def _fetch_all_signals(self) -> List[CompanySignal]:
        target_titles = self._cfg.get("target_titles") or []
        target_industries = self._cfg.get("target_industries") or []
        competitor_techs = self._cfg.get("competitor_technologies") or []
        hiring_depts = self._cfg.get("hiring_departments") or ["sales", "revenue", "growth"]

        tasks = [
            self._signal_monitor.get_job_change_signals(target_titles, target_industries),
            self._signal_monitor.get_funding_signals(),
            self._signal_monitor.get_hiring_surge_signals(hiring_depts),
        ]
        if competitor_techs:
            tasks.append(self._signal_monitor.get_tech_install_signals(competitor_techs))

        gathered = await asyncio.gather(*tasks, return_exceptions=True)
        signals: List[CompanySignal] = []
        for result in gathered:
            if isinstance(result, list):
                signals.extend(result)
            elif isinstance(result, Exception):
                console.print(f"[red]Signal fetch error: {result}[/red]")
        return signals

    # ── Per-signal processing ─────────────────────────────────────────────────

    async def _process_signal(self, signal: CompanySignal) -> Optional[dict]:
        console.print(
            f"\n[bold cyan]{signal.company_name}[/bold cyan] "
            f"[dim]({signal.signal_type.value})[/dim]"
        )

        # Skip domains contacted recently
        if self._dedup.already_emailed(signal.company_domain):
            console.print("  [yellow]Skip — emailed within cooldown window[/yellow]")
            return None

        # Layer 3 — enrich contact
        target_titles = self._cfg.get("target_titles") or []
        contact = await self._apollo_enricher.find_contact(signal, target_titles or None)
        if not contact:
            console.print("  [yellow]Skip — no verified contact found[/yellow]")
            return None

        console.print(f"  Contact: {contact.first_name} {contact.last_name}, {contact.title}")

        enriched = await self._hubspot.enrich_contact(contact, signal)

        if enriched.in_active_deal:
            console.print("  [yellow]Skip — active deal in HubSpot[/yellow]")
            return None

        if enriched.last_contacted:
            days_ago = (datetime.utcnow() - enriched.last_contacted).days
            if days_ago < RECONTACT_COOLDOWN_DAYS:
                console.print(f"  [yellow]Skip — contacted {days_ago}d ago[/yellow]")
                return None

        # Optional LinkedIn enrichment
        if self._apify and contact.linkedin_url:
            console.print("  Fetching LinkedIn profile...")
            enriched.linkedin_data = await self._apify.get_profile(contact.linkedin_url)

        # Layer 4 — generate email
        console.print("  Generating email...")
        try:
            email_output = self._email_gen.generate(
                enriched, sender_name=self._cfg.get("sender_name", "")
            )
        except Exception as e:
            console.print(f"  [red]Email generation failed: {e}[/red]")
            return None

        console.print(f"  [italic]Subject:[/italic] {email_output.subject}")

        if self._cfg.get("dry_run"):
            console.print(f"  [cyan][DRY RUN] Would send to {contact.email}[/cyan]")
            console.print(f"  Body: {email_output.body[:120]}...")
            return {"email": email_output, "dry_run": True}

        # Layer 5 — send email
        try:
            gmail_id = self._gmail.send(
                to=contact.email,
                subject=email_output.subject,
                body=email_output.body,
            )
            console.print(f"  [green]Sent (Gmail: {gmail_id})[/green]")
        except Exception as e:
            console.print(f"  [red]Send failed: {e}[/red]")
            return None

        # Log to HubSpot
        try:
            hs_id = await self._hubspot.upsert_contact(contact)
            await self._hubspot.log_email_activity(
                contact_id=hs_id,
                subject=email_output.subject,
                body=email_output.body,
                signal_type=signal.signal_type.value,
            )
            console.print(f"  [green]Logged to HubSpot (contact: {hs_id})[/green]")
        except Exception as e:
            console.print(f"  [yellow]HubSpot logging failed: {e}[/yellow]")

        # Mark domain as emailed
        self._dedup.mark_emailed(signal.company_domain)

        # Slack notification
        if self._slack:
            try:
                await self._slack.notify(email_output, gmail_id)
            except Exception as e:
                console.print(f"  [yellow]Slack notification failed: {e}[/yellow]")

        return {"email": email_output, "gmail_id": gmail_id}

    # ── Display ───────────────────────────────────────────────────────────────

    def _print_signals_table(self, routed: List[Tuple[CompanySignal, int]]) -> None:
        table = Table(title="Signals to process", show_lines=True)
        table.add_column("#", style="dim", width=3)
        table.add_column("Company", style="cyan")
        table.add_column("Signal", style="magenta")
        table.add_column("Priority", style="yellow")
        table.add_column("Score", style="green", justify="right")

        for i, (signal, score) in enumerate(routed, 1):
            table.add_row(
                str(i),
                signal.company_name,
                signal.signal_type.value.replace("_", " ").title(),
                signal.priority.value.upper(),
                str(score),
            )
        console.print(table)
