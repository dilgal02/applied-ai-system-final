"""Tests for coach_model.py that need neither torch nor the model files."""
import coach_model


def test_missing_dependencies_show_install_help(monkeypatch, capsys):
    monkeypatch.setattr(coach_model, "missing_dependencies", lambda: ["torch"])

    assert coach_model.main(["smoke"]) == 2
    assert coach_model.main(["download"]) == 2

    errors = capsys.readouterr().err
    assert "Missing coach dependencies: torch" in errors
    assert "python -m pip install -r requirements-coach.txt" in errors


def test_missing_model_shows_download_help(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(coach_model, "missing_dependencies", lambda: [])
    monkeypatch.setattr(coach_model, "MODEL_DIR", tmp_path / "no-model")

    # smoke never downloads: it stops and explains what to run.
    assert coach_model.main(["smoke"]) == 2

    errors = capsys.readouterr().err
    assert "does not exist" in errors
    assert "python coach_model.py download" in errors
    assert not (tmp_path / "no-model").exists()


def test_wrong_local_revision_is_rejected(monkeypatch, tmp_path):
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    for name in coach_model.REQUIRED_FILES:
        (model_dir / name).write_text("{}")
    (model_dir / coach_model.REVISION_FILE).write_text("0" * 40 + "\n")
    monkeypatch.setattr(coach_model, "MODEL_DIR", model_dir)

    assert "not the pinned revision" in coach_model.model_problem()

    (model_dir / coach_model.REVISION_FILE).write_text(
        coach_model.MODEL_REVISION + "\n"
    )
    assert coach_model.model_problem() is None


def test_model_is_pinned_and_stored_inside_the_project():
    assert len(coach_model.MODEL_REVISION) == 40
    int(coach_model.MODEL_REVISION, 16)  # a full hexadecimal commit hash
    assert coach_model.MODEL_DIR.is_relative_to(coach_model.PROJECT_ROOT)
    assert coach_model.relative(coach_model.MODEL_DIR) == "models/Qwen3-0.6B"
