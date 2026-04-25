"""
Flask dashboard for reviewing the outreach email queue.

Routes
------
GET  /                           → redirect to /dashboard
GET  /dashboard                  → review UI (HTML)
GET  /api/emails                 → list queue as JSON  (?status=pending|sent|rejected|all)
GET  /api/emails/counts          → {pending:N, sent:N, rejected:N}
POST /api/emails/<id>/approve    → send via Gmail, mark sent
POST /api/emails/<id>/reject     → mark rejected  (body: {"reason": "..."})
POST /api/emails/<id>/edit       → update draft   (body: {"subject":"...","body":"..."})
"""

import os
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request

from ..delivery.gmail import GmailClient
from ..delivery.logger import ActivityLogger
from ..queue.email_queue import EmailQueue
from ..signals.base import Contact, EmailOutput


def create_app(config: dict) -> Flask:
    template_dir = Path(__file__).parent / "templates"
    app = Flask(__name__, template_folder=str(template_dir))
    app.config["JSON_SORT_KEYS"] = False

    queue = EmailQueue(config.get("queue_db", ".agent_state/email_queue.db"))
    gmail = GmailClient(
        credentials_file=config.get(
            "gmail_credentials_file", "credentials/gmail_credentials.json"
        ),
        token_file=config.get(
            "gmail_token_file", "credentials/gmail_token.json"
        ),
    )
    logger = ActivityLogger(config.get("log_file", ".agent_state/sent_log.csv"))

    # ── pages ─────────────────────────────────────────────────────────────────

    @app.route("/")
    def index():
        return redirect("/dashboard")

    @app.route("/dashboard")
    def dashboard():
        return render_template("dashboard.html", counts=queue.counts())

    # ── API ───────────────────────────────────────────────────────────────────

    @app.route("/api/emails")
    def api_list():
        status = request.args.get("status", "pending")
        emails = queue.list_all() if status == "all" else queue.list_by_status(status)
        return jsonify(emails)

    @app.route("/api/emails/counts")
    def api_counts():
        return jsonify(queue.counts())

    @app.route("/api/emails/<row_id>/approve", methods=["POST"])
    def api_approve(row_id: str):
        row = queue.get(row_id)
        if not row:
            return jsonify({"error": "Not found"}), 404
        if row["status"] != "pending":
            return jsonify({"error": f"Email is already '{row['status']}'"}), 409

        try:
            gmail_id = gmail.send(
                to=row["email"],
                subject=row["subject"],
                body=row["body"],
            )
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 503
        except Exception as e:
            return jsonify({"error": f"Gmail error: {e}"}), 500

        queue.mark_sent(row_id, gmail_id)

        # Mirror to CSV activity log
        try:
            contact = Contact(
                first_name=row["first_name"] or "",
                last_name=row["last_name"] or "",
                email=row["email"],
                title=row["title"] or "",
                company_name=row["company_name"] or "",
                company_domain=row["company_domain"] or "",
            )
            email_output = EmailOutput(
                subject=row["subject"],
                body=row["body"],
                contact=contact,
            )
            logger.log(email_output, gmail_id)
        except Exception:
            pass  # logging failure shouldn't block the response

        return jsonify({"ok": True, "gmail_id": gmail_id})

    @app.route("/api/emails/<row_id>/reject", methods=["POST"])
    def api_reject(row_id: str):
        row = queue.get(row_id)
        if not row:
            return jsonify({"error": "Not found"}), 404
        if row["status"] != "pending":
            return jsonify({"error": f"Email is already '{row['status']}'"}), 409

        data = request.get_json(silent=True) or {}
        queue.mark_rejected(row_id, data.get("reason", ""))
        return jsonify({"ok": True})

    @app.route("/api/emails/<row_id>/edit", methods=["POST"])
    def api_edit(row_id: str):
        row = queue.get(row_id)
        if not row:
            return jsonify({"error": "Not found"}), 404

        data = request.get_json(silent=True) or {}
        subject = (data.get("subject") or "").strip()
        body = (data.get("body") or "").strip()

        if not subject or not body:
            return jsonify({"error": "subject and body are required"}), 400

        queue.update_draft(row_id, subject, body)
        return jsonify({"ok": True})

    return app
