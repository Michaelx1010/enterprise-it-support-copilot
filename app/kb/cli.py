"""KB command wiring; the Phase 1 command handlers stay independent."""

import argparse
import json
from pathlib import Path
import sys

import psycopg
from pydantic import ValidationError

from app.kb.ingest import ingest
from app.kb.retrieval import search
from app.kb.store import PgvectorStore
from app.providers.embeddings import EmbeddingError
from app.providers.openai_embeddings import OpenAIEmbeddings
from evaluation.retrieval import evaluate


def add_commands(commands: argparse._SubParsersAction) -> None:
    kb = commands.add_parser("kb", help="Ingest, search, and evaluate Markdown documentation.")
    subcommands = kb.add_subparsers(dest="kb_command", required=True)
    subcommands.add_parser("init", help="Initialize the pgvector extension and dedicated table.")
    ingestion = subcommands.add_parser("ingest", help="Embed and transactionally replace the entire KB index.")
    ingestion.add_argument("--path", type=Path, default=Path("knowledge_base"))
    retrieval = subcommands.add_parser("search", help="Retrieve chunks without generating an answer.")
    retrieval.add_argument("query")
    retrieval.add_argument("--top-k", type=int, default=3)
    evaluation = subcommands.add_parser("evaluate", help="Evaluate section-level retrieval and record distances.")
    evaluation.add_argument("--dataset", type=Path, default=Path("evaluation/retrieval.jsonl"))
    evaluation.add_argument("--top-k", type=int, default=3)
    evaluation.add_argument("--output", type=Path, default=Path("reports/retrieval_evaluation.json"))


def run(args: argparse.Namespace) -> int:
    try:
        store = PgvectorStore.from_environment()
        if args.kb_command == "init":
            store.initialize()
            print("Initialized PostgreSQL/pgvector knowledge-base schema.")
            return 0
        if args.kb_command == "evaluate" and args.output.resolve() == args.dataset.resolve():
            raise ValueError("Evaluation output must differ from the input dataset.")
        embedder = OpenAIEmbeddings.from_environment()
        try:
            if args.kb_command == "ingest":
                output = ingest(args.path, embedder=embedder, store=store)
            elif args.kb_command == "search":
                output = [result.model_dump() for result in search(
                    args.query, embedder=embedder, store=store, top_k=args.top_k,
                )]
            else:
                report = evaluate(args.dataset, embedder=embedder, store=store, top_k=args.top_k)
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
                output = {"report": str(args.output), "aggregates": report["aggregates"]}
        finally:
            embedder.client.close()
        print(json.dumps(output, indent=2))
    except psycopg.Error as exc:
        print(f"Error: PostgreSQL operation failed ({type(exc).__name__}). "
              "Check the local database configuration, service, and kb init.", file=sys.stderr)
        return 1
    except ValidationError:
        print("Error: invalid document, embedding configuration, or evaluation record.", file=sys.stderr)
        return 1
    except (EmbeddingError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0
