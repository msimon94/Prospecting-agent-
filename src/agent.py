from typing import List, Optional

from rich.console import Console
from rich.table import Table

from .signals.base import Contact, EmailOutput
from .loader.contact_loader import load_contacts
from .orchestration.deduplicator import ContactDeduplicator
from .ai.email_generator import EmailGenerator
from .delivery.gmail import GmailClient
from .delivery.slack import SlackNotifier
from .delivery.logger import ActivityLogger

console = Console()


class ProspectingAgent:
    def __init__(self, config: dict):
        self._cfg = config
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
        self._dedup = ContactDeduplicator()
        self._logger = ActivityLogger(
            config.get("log_file", ".agent_state/sent_log.csv")
        )

    # ── Main entry point ──────────────────────────────────────────────────────

    async def run(self, contact_file: str) -> List[dict]:
        console.rule("[bold blue]Prospecting Agent")

        # Load list
        console.print(f"Loading contacts from [cyan]{contact_file}[/cyan]...")
        all_contacts = load_contacts(contact_file)
        if not all_contacts:
            console.print("[yellow]No contacts found in file. Exiting.[/yellow]")
            return []

        # Deduplicate against prior runs
        new_contacts = self._dedup.filter_new(all_contacts)
        already_sent = len(all_contacts) - len(new_contacts)
        console.print(
            f"[green]{len(new_contacts)} new[/green] contacts "
            f"([dim]{already_sent} already emailed, skipped[/dim])"
        )

        if not new_contacts:
            console.print("[yellow]Everyone on this list has already been contacted.[/yellow]")
            return []

        # Cap per run
        max_emails = self._cfg.get("max_emails_per_run", 50)
        batch = new_contacts[:max_emails]
        if len(new_contacts) > max_emails:
            console.print(
                f"[dim]Capping at {max_emails} per run "
                f"({len(new_contacts) - max_emails} will be sent next run)[/dim]"
            )

        self._print_preview(batch)

        results = []
        for contact in batch:
            result = self._process_contact(contact)
            if result:
                results.append(result)

        console.rule(f"[bold green]Done — {len(results)}/{len(batch)} emails sent")
        return results

    # ── Per-contact processing ────────────────────────────────────────────────

    def _process_contact(self, contact: Contact) -> Optional[dict]:
        name = f"{contact.first_name} {contact.last_name}".strip() or contact.email
        console.print(f"\n[bold cyan]{name}[/bold cyan] — {contact.title} @ {contact.company_name}")

        # Safety check: cross-reference the persistent log as well as dedup store
        if self._logger.already_sent(contact.email):
            console.print("  [yellow]Skip — found in sent log[/yellow]")
            return None

        # Generate email
        console.print("  Generating email...")
        try:
            email_output = self._email_gen.generate(
                contact, sender_name=self._cfg.get("sender_name", "")
            )
        except Exception as e:
            console.print(f"  [red]Generation failed: {e}[/red]")
            return None

        console.print(f"  [italic]Subject:[/italic] {email_output.subject}")

        if self._cfg.get("dry_run"):
            console.print(f"  [cyan][DRY RUN] Would send to {contact.email}[/cyan]")
            console.print(f"  {email_output.body[:120]}...")
            return {"email": email_output, "dry_run": True}

        # Send
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

        # Log locally
        self._logger.log(email_output, gmail_id)
        self._dedup.mark_sent(contact.email)

        # Slack
        if self._slack:
            import asyncio
            try:
                asyncio.get_event_loop().run_until_complete(
                    self._slack.notify_list(email_output, gmail_id)
                )
            except Exception as e:
                console.print(f"  [yellow]Slack notification failed: {e}[/yellow]")

        return {"email": email_output, "gmail_id": gmail_id}

    # ── Display ───────────────────────────────────────────────────────────────

    def _print_preview(self, contacts: List[Contact]) -> None:
        table = Table(title=f"Batch — {len(contacts)} contacts", show_lines=False)
        table.add_column("#", style="dim", width=4)
        table.add_column("Name", style="cyan")
        table.add_column("Title", style="white")
        table.add_column("Company", style="magenta")
        table.add_column("Email", style="dim")

        for i, c in enumerate(contacts, 1):
            table.add_row(
                str(i),
                f"{c.first_name} {c.last_name}".strip(),
                c.title or "",
                c.company_name,
                c.email or "",
            )
        console.print(table)
