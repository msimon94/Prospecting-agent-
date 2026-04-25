#!/usr/bin/env python3
"""
AI Prospecting Agent CLI

Usage:
  python main.py auth                          # Authorize Gmail (run once)
  python main.py run contacts.csv              # Run against a contact list
  python main.py run contacts.csv --dry-run    # Preview emails, don't send
  python main.py run contacts.csv --max 20     # Cap emails this run
"""
import asyncio

import click
from rich.console import Console

from config.settings import load_config
from src.agent import ProspectingAgent
from src.delivery.gmail import GmailClient

console = Console()


@click.group()
def cli():
    """AI Prospecting Agent — import a list, send personalized outreach."""
    pass


@cli.command()
def auth():
    """Run the Gmail OAuth flow and save your token."""
    config = load_config()
    client = GmailClient(
        credentials_file=config["gmail_credentials_file"],
        token_file=config["gmail_token_file"],
    )
    console.print("[bold]Starting Gmail OAuth flow...[/bold]")
    console.print("A browser window will open. Sign in and grant send permission.")
    client.authorize()
    console.print("[green]Authorization complete. Token saved.[/green]")


@cli.command()
@click.argument("contact_file", type=click.Path(exists=True))
@click.option("--dry-run", is_flag=True, help="Generate emails but don't send them.")
@click.option("--max", "max_emails", type=int, default=None, help="Cap emails this run.")
def run(contact_file: str, dry_run: bool, max_emails: int):
    """
    Generate and send personalized emails to every contact in CONTACT_FILE.

    CONTACT_FILE can be a .csv or .xlsx file. Required columns:
    first_name, last_name, email, company.
    Optional: title, industry, employee_count, context/notes.
    """
    config = load_config()
    if dry_run:
        config["dry_run"] = True
    if max_emails is not None:
        config["max_emails_per_run"] = max_emails

    agent = ProspectingAgent(config)
    asyncio.run(agent.run(contact_file))


if __name__ == "__main__":
    cli()
