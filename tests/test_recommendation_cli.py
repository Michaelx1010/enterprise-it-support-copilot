import json
from unittest.mock import Mock

import psycopg
import pytest

from app.cli import main
from app.providers.recommendation import RecommendationError
from app.rag import cli
from app.rag.schemas import RecommendationResult, SupportRecommendation

ARGS = ["recommend", "--subject", "VPN", "--description", "Gateway unavailable"]


@pytest.fixture
def adapters(monkeypatch):
    embedder, provider, store = Mock(), Mock(), Mock()
    provider.model = "fixture-model"
    monkeypatch.setattr(cli.OpenAIEmbeddings, "from_environment", Mock(return_value=embedder))
    monkeypatch.setattr(cli.OpenAIRecommendation, "from_environment", Mock(return_value=provider))
    monkeypatch.setattr(cli.PgvectorStore, "from_environment", Mock(return_value=store))
    return embedder, provider, store


def test_cli_serializes_evidence_and_closes_clients(monkeypatch, capsys, adapters, evidence, recommendation_payload):
    result = RecommendationResult(recommendation=SupportRecommendation.model_validate(recommendation_payload),
                                  evidence=evidence)
    run = Mock(return_value=result)
    monkeypatch.setattr(cli, "recommend", run)
    assert main(ARGS) == 0
    assert json.loads(capsys.readouterr().out) == result.model_dump()
    assert run.call_args.args[0].subject == "VPN"
    assert run.call_args.kwargs["top_k"] == 3
    for adapter in adapters[:2]:
        adapter.client.close.assert_called_once()


@pytest.mark.parametrize("args", [
    ["recommend", "--subject", " ", "--description", "text"],
    ARGS + ["--top-k", "0"],
    ["recommend", "--subject", "Long", "--description", "x" * 6000],
])
def test_invalid_input_fails_before_clients(args, adapters):
    assert main(args) == 1
    cli.OpenAIEmbeddings.from_environment.assert_not_called()
    cli.OpenAIRecommendation.from_environment.assert_not_called()


@pytest.mark.parametrize("error", [RecommendationError("private content"), psycopg.OperationalError("secret URL")])
def test_cli_failure_is_sanitized(monkeypatch, capsys, adapters, error):
    monkeypatch.setattr(cli, "recommend", Mock(side_effect=error))
    assert main(ARGS) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "private content" not in output.err
    assert "secret URL" not in output.err
    for adapter in adapters[:2]:
        adapter.client.close.assert_called_once()


def test_client_cleanup_if_second_adapter_initialization_fails(monkeypatch, adapters):
    monkeypatch.setattr(cli.OpenAIRecommendation, "from_environment", Mock(side_effect=ValueError("Missing model")))
    assert main(ARGS) == 1
    adapters[0].client.close.assert_called_once()


def test_evaluation_writes_report_and_returns_nonzero_for_failures(tmp_path, monkeypatch, capsys, adapters):
    report = {"aggregates": {"failed": 1, "rejected": 0}, "cases": []}
    monkeypatch.setattr(cli, "evaluate", Mock(return_value=report))
    output = tmp_path / "report.json"
    assert main(["recommend-evaluate", "--output", str(output)]) == 1
    assert json.loads(output.read_text()) == report
    assert json.loads(capsys.readouterr().out)["aggregates"]["failed"] == 1


def test_evaluation_never_overwrites_input(adapters):
    assert main(["recommend-evaluate", "--output", "evaluation/recommendation.jsonl"]) == 1
    cli.OpenAIEmbeddings.from_environment.assert_not_called()
