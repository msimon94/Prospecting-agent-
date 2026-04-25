import asyncio
from typing import List, Optional

from rich.console import Console
from rich.table import Table

from .signals.base import Company, Contact, EmailOutput
from .loader.company_loader import load_companies
from .orchestration.deduplicator import CompanyDeduplicator
from .discovery.contact_discoverer import ContactDiscoverer
from .ai.email_generator import EmailGenerator
from .delivery.gmail import GmailClient
from .delivery.slack import SlackNotifier
from .delivery.logger import ActivityLogger

console = Console()


class ProspectingAgent:
    def __init__(self, config: dict, queue=None):
        """
        queue: an EmailQueue instance.  When provided the agent writes
               generated emails to SQLite instead of sending immediately.
               Pass None (default) for direct-send mode.
        """
        self._cfg = config
        self._queue = queue  # EmailQueue | None

        self._discoverer = ContactDiscoverer(
            apollo_api_key=config.get("apollo_api_key"),
            leadiq_api_key=config.get("leadiq_api_key"),
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
        self._dedup = CompanyDeduplicator(
            ttl_days=config.get("recontact_ttl_days", 90)
        )
        self._logger = ActivityLogger(
            config.get("log_file", ".agent_state/sent_log.csv")
        )

    # ── Main entry point ──────────────────────────────────────────────────────

    async def run(self, company_file: str) -> List[dict]:
        mode = "queue" if self._queue else "send"
        console.rule(f"[bold blue]Prospecting Agent[/bold blue] [dim]({mode} mode)[/dim]")

        console.print(f"Loading companies from [cyan]{company_file}[/cyan]...")
        all_companies = load_companies(company_file)
        if not all_companies:
            console.print("[yellow]No companies found in file.[/yellow]")
            return []

        new_companies = self._dedup.filter_new(all_companies)
        already_done = len(all_companies) - len(new_companies)
        console.print(
            f"[green]{len(new_companies)} new[/green] companies to process"
            + (f" ([dim]{already_done} already processed, skipped[/dim])" if already_done else "")
        )

        if not new_companies:
            console.print("[yellow]All companies on this list have already been contacted.[/yellow]")
            return []

        max_per_run = self._cfg.get("max_emails_per_run", 25)
        batch = new_companies[:max_per_run]
        if len(new_companies) > max_per_run:
            console.print(
                f"[dim]Processing {max_per_run} this run; "
                f"{len(new_companies) - max_per_run} queued for next run[/dim]"
            )

        self._print_companies(batch)

        results = []
        for company in batch:
            result = await self._process_company(company)
            if result:
                results.append(result)

        action = "queued for review" if self._queue else "emails sent"
        console.rule(f"[bold green]Done — {len(results)}/{len(batch)} {action}")
        return results

    # ── Per-company pipeline ──────────────────────────────────────────────────

    async def _process_company(self, company: Company) -> Optional[dict]:
        console.print(f"\n[bold cyan]{company.name}[/bold cyan] — [dim]{company.domain}[/dim]")

        # ── Contact discovery ─────────────────────────────────────────────────
        console.print("  Discovering contacts (Apollo → website → LinkedIn)...")
        try:
            contact = await self._discoverer.discover(company)
        except Exception as e:
            console.print(f"  [red]Discovery error: {e}[/red]")
            self._dedup.mark_processed(company.domain)
            return None

        if not contact:
            console.print("  [yellow]No emailable contact found — skipping[/yellow]")
            self._dedup.mark_processed(company.domain)
            return None

        src_label = f"[dim]via {contact.source}[/dim]" if contact.source else ""
        console.print(
            f"  Found: [bold]{contact.first_name} {contact.last_name}[/bold], "
            f"{contact.title} {src_label}"
        )

        # ── Email generation ──────────────────────────────────────────────────
        console.print("  Generating email with Claude...")
        try:
            email_output = self._email_gen.generate(
                contact, sender_name=self._cfg.get("sender_name", "")
            )
        except Exception as e:
            console.print(f"  [red]Generation failed: {e}[/red]")
            return None

        console.print(f"  [italic]Subject:[/italic] {email_output.subject}")

        # ── Queue mode: save for dashboard review ─────────────────────────────
        if self._queue is not None:
            row_id = self._queue.enqueue(email_output)
            self._dedup.mark_processed(company.domain)
            console.print(f"  [cyan]Queued for review (id: {row_id[:8]}…)[/cyan]")
            return {"queued": True, "id": row_id, "email": email_output}

        # ── Dry-run mode ──────────────────────────────────────────────────────
        if self._cfg.get("dry_run"):
            console.print(f"  [cyan][DRY RUN] Would send to {contact.email}[/cyan]")
            console.print(f"  {email_output.body}")
            self._dedup.mark_processed(company.domain)
            return {"email": email_output, "dry_run": True}

        # ── Direct send mode ──────────────────────────────────────────────────
        try:
            gmail_id = self._gmail.send(
                to=contact.email,
                subject=email_output.subject,
                body=email_output.body,
            )
            console.print(f"  [green]Sent to {contact.email} (Gmail: {gmail_id})[/green]")
        except Exception as e:
            console.print(f"  [red]Send failed: {e}[/red]")
            return None

        self._logger.log(email_output, gmail_id)
        self._dedup.mark_processed(company.domain)

        if self._slack:
            try:
                await self._slack.notify_list(email_output, gmail_id)
            except Exception as e:
                console.print(f"  [yellow]Slack failed: {e}[/yellow]")

        return {"email": email_output, "gmail_id": gmail_id}

    # ── Display ───────────────────────────────────────────────────────────────

    def _print_companies(self, companies: List[Company]) -> None:
        table = Table(title=f"Batch — {len(companies)} companies", show_lines=False)
        table.add_column("#", style="dim", width=4)
        table.add_column("Company", style="cyan")
        table.add_column("Domain", style="dim")
        table.add_column("Industry", style="white")
        table.add_column("Notes", style="magenta")

        for i, c in enumerate(companies, 1):
            table.add_row(
                str(i),
                c.name,
                c.domain,
                c.industry or "",
                (c.context or "")[:40],
            )
        console.print(table)
