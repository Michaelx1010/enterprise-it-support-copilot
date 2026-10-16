"""Thin CLI composition of the existing retrieval and new generation adapters."""

import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import sys

import psycopg
from pydantic import ValidationError

from app.kb.store import PgvectorStore
from app.providers.embeddings import EmbeddingError
from app.providers.openai_embeddings import OpenAIEmbeddings
from app.providers.openai_recommendation import MAX_OUTPUT_TOKENS, TEMPERATURE, OpenAIRecommendation
from app.providers.recommendation import RecommendationError
from app.rag.recommendation import build_query, recommend
from app.schemas import TicketInput
from evaluation.recommendation import evaluate, load_cases


def add_commands(commands: argparse._SubParsersAction) -> None:
    recommendation = commands.add_parser("recommend", help="Recommend actions grounded in retrieved KB evidence.")
    recommendation.add_argument("--subject", required=True)
    recommendation.add_argument("--description", required=True)
    recommendation.add_argument("--top-k", type=int, default=3)
    evaluation = commands.add_parser("recommend-evaluate", help="Evaluate recommendations; makes paid model calls.")
    evaluation.add_argument("--dataset", type=Path, default=Path("evaluation/recommendation.jsonl"))
    evaluation.add_argument("--output", type=Path, default=Path("reports/recommendation_evaluation.json"))
    evaluation.add_argument("--top-k", type=int, default=3)


def run(args: argparse.Namespace) -> int:
    try:
        if not 1 <= args.top_k <= 50:
            raise ValueError("top_k must be between 1 and 50.")
        if args.command == "recommend":
            ticket = TicketInput(subject=args.subject, description=args.description)
            build_query(ticket)
        else:
            if args.output.resolve() == args.dataset.resolve():
                raise ValueError("Evaluation output must differ from the input dataset.")
            load_cases(args.dataset)
        store = PgvectorStore.from_environment()
        with ExitStack() as stack:
            embedder = OpenAIEmbeddings.from_environment()
            stack.callback(embedder.client.close)
            provider = OpenAIRecommendation.from_environment()
            stack.callback(provider.client.close)
            if args.command == "recommend":
                output = recommend(ticket, embedder=embedder, store=store,
                                   provider=provider, top_k=args.top_k).model_dump()
            else:
                report = evaluate(args.dataset, embedder=embedder, store=store, provider=provider,
                                  top_k=args.top_k, generation_settings={
                                      "provider": "openai", "model": provider.model,
                                      "max_output_tokens": MAX_OUTPUT_TOKENS, "temperature": TEMPERATURE,
                                      "store": False,
                                  })
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
                print(json.dumps({"report": str(args.output), "aggregates": report["aggregates"]}, indent=2))
                return 1 if report["aggregates"]["failed"] or report["aggregates"]["rejected"] else 0
        print(json.dumps(output, indent=2))
    except psycopg.Error:
        print("Error: recommendation retrieval failed; check the database service and KB index.", file=sys.stderr)
        return 1
    except ValidationError:
        print("Error: invalid ticket, recommendation, or evaluation record.", file=sys.stderr)
        return 1
    except (RecommendationError, EmbeddingError):
        print("Error: recommendation or embedding failed validation or generation; no recommendation accepted.", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except OSError:
        print("Error: could not read or write the evaluation files.", file=sys.stderr)
        return 1
    return 0
