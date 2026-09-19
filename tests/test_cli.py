import json

from cutover.cli import main


def test_onboard_reports_blocked_with_next_questions(tmp_path, capsys):
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps({"project_name": "acme"}), encoding="utf-8")
    assert main(["onboard", "--answers", str(answers)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "blocked"
    assert "source_systems" in output["next_questions"]


def test_onboard_reports_ready(tmp_path, capsys):
    answers = tmp_path / "answers.json"
    answers.write_text(
        json.dumps({"project_name": "acme", "source_systems": ["snowflake"], "targets": ["databricks"], "unity_catalog_enabled": True}),
        encoding="utf-8",
    )
    assert main(["onboard", "--answers", str(answers)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ready"
