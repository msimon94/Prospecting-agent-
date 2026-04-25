#!/usr/bin/env python3
"""
AI Prospecting Agent CLI

Usage:
  python main.py auth           # Authorize Gmail (run once)
  python main.py run            # Run the agent once
  python main.py run --dry-run  # Preview emails, don't send
  python main.py watch          # Run on a schedule (default: every 6 hours)
"""
import asyncio
import time

import click
from rich.console import Console

from config.settings import load_config
from src.agent import ProspectingAgent
from src.delivery.gmail import GmailClient

console = Console()


@click.group()
def cli():
    """AI Prospecting Agent — intent signals → personalized outreach."""
    pass


@cli.command()
def auth():
    """Run the Gmail OAuth flow and save the token."""
    config = load_config()
    client = GmailClient(
        credentials_file=config["gmail_credentials_file"],
        token_file=config["gmail_token_file"],
    )
    console.print("[bold]Starting Gmail OAuth flow...[/bold]")
    console.print("A browser window will open. Sign in and grant send permission.")
    client.authorize()
    console.print("[green]Authorization complete.[/green]")


@cli.command()
@click.option("--dry-run", is_flag=True, help="Generate emails but don't send or log.")
@click.option("--max-emails", type=int, default=None, help="Cap emails sent this run.")
def run(dry_run: bool, max_emails: int):
    """Run the agent once against live intent signals."""
    config = load_config()
    if dry_run:
        config["dry_run"] = True
    if max_emails is not None:
        config["max_emails_per_run"] = max_emails

    agent = ProspectingAgent(config)
    asyncio.run(agent.run())


@cli.command()
@click.option(
    "--interval",
    default=360,
    show_default=True,
    help="Polling interval in minutes.",
)
@click.option("--dry-run", is_flag=True)
def watch(interval: int, dry_run: bool):
    """Run the agent on a recurring schedule."""
    import schedule

    config = load_config()
    if dry_run:
        config["dry_run"] = True

    agent = ProspectingAgent(config)

    async def job():
        await agent.run()

    console.print(f"[bold green]Watching — will run every {interval} minutes.[/bold green]")
    console.print("Press Ctrl+C to stop.\n")

    # Fire immediately, then on schedule
    asyncio.run(job())
    schedule.every(interval).minutes.do(lambda: asyncio.run(job()))

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    cli()
