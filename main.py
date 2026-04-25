#!/usr/bin/env python3
"""
AI Prospecting Agent

Commands
--------
auth                   Run Gmail OAuth flow (once)
run   COMPANY_FILE     Discover contacts + send emails
                         --queue     Save to review queue instead of sending
                         --dry-run   Generate only, don't send or queue
                         --max N     Cap companies processed this run
serve                  Start the review dashboard on http://localhost:5000
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
    """AI Prospecting Agent — import companies, find contacts, send personalized outreach."""
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
@click.option("--queue",    "use_queue", is_flag=True, help="Save emails to review queue instead of sending immediately.")
@click.option("--dry-run",  is_flag=True,               help="Generate emails but don't send or queue them.")
@click.option("--max", "max_emails", type=int, default=None, help="Cap companies processed this run.")
def run(company_file: str, use_queue: bool, dry_run: bool, max_emails: int):
    """
    For each company in COMPANY_FILE: discover the best contact, generate a
    personalized email, then either send it or queue it for dashboard review.

    COMPANY_FILE can be .csv or .xlsx.
    Required column: domain (or website).
    Optional: company_name, industry, employee_count, context/notes.
    """
    config = load_config()
    if dry_run:
        config["dry_run"] = True
    if max_emails is not None:
        config["max_emails_per_run"] = max_emails

    queue = None
    if use_queue:
        from src.queue.email_queue import EmailQueue
        queue = EmailQueue(config.get("queue_db", ".agent_state/email_queue.db"))
        console.print(f"[cyan]Queue mode — emails will appear in the dashboard.[/cyan]")

    agent = ProspectingAgent(config, queue=queue)
    asyncio.run(agent.run(company_file))

    if use_queue:
        console.print("\n[green]Open http://localhost:5000 to review and approve emails.[/green]")
        console.print("[dim]Start the dashboard with: python main.py serve[/dim]")


@cli.command()
@click.option("--port", default=5000, show_default=True, help="Port to listen on.")
@click.option("--host", default="127.0.0.1", show_default=True, help="Host to bind.")
def serve(port: int, host: str):
    """
    Start the email review dashboard.

    Open http://localhost:5000/dashboard to approve, edit, or reject
    emails generated with `python main.py run --queue`.
    """
    try:
        from flask import Flask
    except ImportError:
        console.print("[red]Flask is not installed. Run: pip install flask[/red]")
        raise SystemExit(1)

    from src.dashboard.app import create_app

    config = load_config()
    app = create_app(config)

    console.print(f"[bold green]Dashboard running → http://{host}:{port}/dashboard[/bold green]")
    app.run(host=host, port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    cli()
