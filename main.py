#!/usr/bin/env python3
"""
AI Prospecting Agent CLI

Usage:
  python main.py auth                           # Authorize Gmail (run once)
  python main.py run companies.csv              # Run against a company list
  python main.py run companies.csv --dry-run    # Preview emails, don't send
  python main.py run companies.csv --max 10     # Cap emails this run
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
    """AI Prospecting Agent — import a company list, auto-find contacts, send personalized outreach."""
    pass


@cli.command()
def auth():
    """Run the Gmail OAuth flow and save your token (do this once)."""
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
@click.argument("company_file", type=click.Path(exists=True))
@click.option("--dry-run", is_flag=True, help="Find contacts and generate emails, but don't send.")
@click.option("--max", "max_emails", type=int, default=None, help="Cap companies processed this run.")
def run(company_file: str, dry_run: bool, max_emails: int):
    """
    For each company in COMPANY_FILE: discover the best contact
    (CEO/CRO/VP Sales/Marketing/Ops), generate a personalized email
    with Claude, and send it from your Gmail inbox.

    COMPANY_FILE can be .csv or .xlsx.
    Required columns: domain (or website).
    Optional: company_name, industry, employee_count, context/notes.
    """
    config = load_config()
    if dry_run:
        config["dry_run"] = True
    if max_emails is not None:
        config["max_emails_per_run"] = max_emails

    agent = ProspectingAgent(config)
    asyncio.run(agent.run(company_file))


if __name__ == "__main__":
    cli()
