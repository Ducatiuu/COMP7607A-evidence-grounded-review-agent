import pytest

from src.schemas import Record, RecordSet
from src.ui_state import UIWorkspace, clear_workspace, load_workspace, new_session_token, save_workspace


def test_workspace_survives_new_session_and_can_be_cleared(tmp_path, monkeypatch):
    monkeypatch.setenv("ABSA_UI_SESSION_DIR", str(tmp_path))
    token = new_session_token()
    workspace = UIWorkspace(source_label="synthetic", records=RecordSet(records=[Record(record_id="R1", text="Nice food")]))
    save_workspace(token, workspace)
    assert load_workspace(token) == workspace
    clear_workspace(token)
    assert load_workspace(token) == UIWorkspace()


def test_session_token_cannot_escape_workspace_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("ABSA_UI_SESSION_DIR", str(tmp_path))
    with pytest.raises(ValueError):
        load_workspace("../secret")
