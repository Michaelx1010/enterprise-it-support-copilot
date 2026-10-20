"""Small command-line entry point for the Phase 1 workflow."""

import argparse
from pathlib import Path
import sys
from urllib.error import URLError

from pydantic import ValidationError

from app.classification import classify_ticket
from app.data import DEFAULT_DATA_PATH, download_dataset, load_tickets
from app.profiling import render_report
from app.providers.base import ClassificationError
from app.schemas import TicketInput


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Explore and classify IT helpdesk tickets.")
    commands = parser.add_subparsers(dest="command", required=True)
    download = commands.add_parser("download", help="Download the pinned dataset CSV.")
    download.add_argument("--output", type=Path, default=DEFAULT_DATA_PATH)
    inspect = commands.add_parser("inspect", help="Write a descriptive dataset report.")
    inspect.add_argument("--data", type=Path, default=DEFAULT_DATA_PATH)
    inspect.add_argument("--output", type=Path, default=Path("reports/dataset_profile.md"))
    classify = commands.add_parser("classify", help="Classify one ticket using OpenAI.")
    classify.add_argument("--subject", required=True)
    classify.add_argument("--description", required=True)
    from app.kb.cli import add_commands, run as run_kb

    add_commands(commands)
    from app.rag.cli import add_commands as add_rag_commands, run as run_rag

    add_rag_commands(commands)
    from app.operations.cli import add_commands as add_ops_commands, run as run_ops

    add_ops_commands(commands)
    args = parser.parse_args(argv)

    if args.command == "kb":
        return run_kb(args)
    if args.command in ("recommend", "recommend-evaluate"):
        return run_rag(args)
    if args.command == "ops":
        return run_ops(args)

    try:
        if args.command == "download":
            print(f"Downloaded {download_dataset(args.output)}")
        elif args.command == "inspect":
            if args.data.resolve() == args.output.resolve():
                raise ValueError("Report output must differ from the source dataset.")
            report = render_report(load_tickets(args.data), args.data)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(report, encoding="utf-8")
            print(f"Wrote {args.output}")
        else:
            # Validate before constructing a client or looking for credentials.
            ticket = TicketInput(subject=args.subject, description=args.description)
            from app.providers.openai import OpenAIProvider

            provider = OpenAIProvider.from_environment()
            try:
                result = classify_ticket(ticket.subject, ticket.description, provider=provider)
            finally:
                provider.client.close()
            print(result.model_dump_json(indent=2))
    except ValidationError:
        print("Error: subject and description must both contain nonblank text.", file=sys.stderr)
        return 1
    except (ClassificationError, OSError, ValueError, URLError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
