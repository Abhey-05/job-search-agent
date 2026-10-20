"""Command-line entry point: `python -m app <command>`."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from app import actions
from app.db import get_db
from app.settings import load_settings


def _setup_logging():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass


def cmd_run(args):
    from app.pipeline import Runner
    db = get_db()
    config = load_settings(db)
    runner = Runner(db, config)
    summary = runner.run()
    print(json.dumps(summary.as_dict(), indent=2, default=str))
    db.close()


def cmd_rerank(args):
    from app.pipeline import Runner, RunSummary
    db = get_db()
    config = load_settings(db)
    run_id = db.start_run(config.mode)
    summary = RunSummary(run_id=run_id, mode=config.mode)
    Runner(db, config).rerank_all(run_id, summary)
    db.finish_run(run_id, "completed", summary.as_dict())
    print(json.dumps(summary.as_dict(), indent=2, default=str))
    db.close()


def cmd_status(args):
    db = get_db()
    config = load_settings(db)
    snapshot = db.dashboard_snapshot()
    print(f"Database: {db.dialect} ({db.database_url.split('@')[-1] if '@' in db.database_url else db.database_url})")
    print(f"Mode: {config.mode}  Paused: {db.get_paused(default=config.paused)}")
    print(f"Active jobs tracked: {len(snapshot['jobs'])}")
    print(f"Pending email approvals: {len(snapshot['pending_emails'])}")
    print(f"Pending application approvals: {len(snapshot['pending_applications'])}")
    print(f"Sent emails: {len(snapshot['sent_emails'])}")
    print(f"Submitted applications: {len(snapshot['submitted_applications'])}")
    print(f"Run history (most recent {len(snapshot['runs'])}):")
    for r in snapshot["runs"]:
        print(f"  run {r['id']}: {r['status']} started {r['started_at']}")
    db.close()


def cmd_dashboard(args):
    from app.dashboard.server import create_app
    flask_app = create_app()
    host = args.host or "0.0.0.0"
    port = args.port or int(os.environ.get("PORT", 8765))
    print(f"Dashboard running at http://{host}:{port}")
    flask_app.run(host=host, port=port, debug=False)


def cmd_import_resume(args):
    from app.resume_store import import_resume
    path = Path(args.path)
    if not path.exists():
        print(f"No such file: {path}")
        sys.exit(1)
    content_type = "application/pdf" if path.suffix.lower() == ".pdf" else "text/plain"
    db = get_db()
    config = load_settings(db)
    resume_id = import_resume(db, config, filename=path.name, content_type=content_type,
                               data=path.read_bytes())
    print(f"Imported resume_files.id={resume_id} ({path.name})")
    db.close()


def cmd_scheduler(args):
    """Convenience local scheduler (APScheduler). Not needed on Render/Railway,
    which run `python -m app run` directly on their own cron trigger -- this is
    for running the agent unattended on a machine/VM with no platform cron."""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from app.pipeline import Runner
    from app.schedule_utils import apscheduler_trigger_args

    db = get_db()
    config = load_settings(db)
    db.close()  # each run opens its own connection

    trigger_kwargs = apscheduler_trigger_args(config.schedule)
    scheduler = BlockingScheduler()

    def job():
        db = get_db()
        cfg = load_settings(db)
        runner = Runner(db, cfg)
        summary = runner.run()
        logging.info("Scheduled run completed: %s", json.dumps(summary.as_dict(), default=str))
        db.close()

    scheduler.add_job(job, "cron", **trigger_kwargs)
    print(f"Local scheduler started. Trigger: {trigger_kwargs}. Ctrl+C to stop.")
    scheduler.start()


def cmd_approve_email(args):
    db = get_db()
    config = load_settings(db)
    result = actions.approve_email(db, config, args.id)
    print(json.dumps(result, indent=2))
    db.close()
    sys.exit(0 if result.get("ok") else 1)


def cmd_reject_email(args):
    db = get_db()
    result = actions.reject_email(db, args.id, note=args.note or "")
    print(json.dumps(result, indent=2))
    db.close()


def cmd_approve_application(args):
    db = get_db()
    config = load_settings(db)
    result = actions.approve_application(db, config, args.id)
    print(json.dumps(result, indent=2))
    db.close()


def cmd_submit_application(args):
    db = get_db()
    result = actions.mark_application_submitted(db, args.id, follow_up_in_days=args.follow_up_days)
    print(json.dumps(result, indent=2))
    db.close()


def cmd_reject_application(args):
    db = get_db()
    result = actions.reject_application(db, args.id, note=args.note or "")
    print(json.dumps(result, indent=2))
    db.close()


def cmd_pause(args):
    db = get_db()
    actions.pause(db)
    print("Execution paused. No emails will be sent or applications submitted until `resume`.")
    db.close()


def cmd_resume(args):
    db = get_db()
    actions.resume(db)
    print("Execution resumed.")
    db.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app", description="Job-search agent")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("run", help="Run one full discovery-through-execution pass").set_defaults(func=cmd_run)
    sub.add_parser("rerank", help="Re-score every active job against current preferences").set_defaults(func=cmd_rerank)
    sub.add_parser("status", help="Print a quick status summary").set_defaults(func=cmd_status)

    p_dash = sub.add_parser("dashboard", help="Start the local/production dashboard web server")
    p_dash.add_argument("--host", default=None)
    p_dash.add_argument("--port", type=int, default=None)
    p_dash.set_defaults(func=cmd_dashboard)

    p_ir = sub.add_parser("import-resume", help="Import a resume file (PDF/txt/md) from local disk")
    p_ir.add_argument("path")
    p_ir.set_defaults(func=cmd_import_resume)

    sub.add_parser("scheduler", help="Run a local APScheduler loop (for machines with no platform cron)"
                   ).set_defaults(func=cmd_scheduler)

    p_ae = sub.add_parser("approve-email", help="Approve and send a drafted email")
    p_ae.add_argument("id", type=int)
    p_ae.set_defaults(func=cmd_approve_email)

    p_re = sub.add_parser("reject-email", help="Reject a drafted email")
    p_re.add_argument("id", type=int)
    p_re.add_argument("--note", default="")
    p_re.set_defaults(func=cmd_reject_email)

    p_aa = sub.add_parser("approve-application", help="Approve a prepared application")
    p_aa.add_argument("id", type=int)
    p_aa.set_defaults(func=cmd_approve_application)

    p_sa = sub.add_parser("submit-application", help="Record that an approved application was manually submitted")
    p_sa.add_argument("id", type=int)
    p_sa.add_argument("--follow-up-days", type=int, default=7)
    p_sa.set_defaults(func=cmd_submit_application)

    p_ra = sub.add_parser("reject-application", help="Reject a prepared application")
    p_ra.add_argument("id", type=int)
    p_ra.add_argument("--note", default="")
    p_ra.set_defaults(func=cmd_reject_application)

    sub.add_parser("pause", help="Immediately pause all external actions").set_defaults(func=cmd_pause)
    sub.add_parser("resume", help="Resume external actions").set_defaults(func=cmd_resume)

    return parser


def main(argv=None):
    _setup_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
