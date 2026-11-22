from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.data_loader import dataset_fingerprint
from src.schemas import Coverage, ExtractionDataset, ExtractionResult


APP = str(Path(__file__).resolve().parents[1] / "app.py")
DEMO_CSV = (Path(__file__).resolve().parents[1] / "data" / "demo" / "core.csv").read_bytes()


def test_demo_upload_extract_ask_compare_and_restore_after_refresh(tmp_path, monkeypatch):
    monkeypatch.setenv("ABSA_UI_SESSION_DIR", str(tmp_path))
    at = AppTest.from_file(APP).run()
    assert not at.exception
    token = at.query_params["session"]
    at.radio(key="source_mode").set_value("Upload CSV").run()
    at.file_uploader(key="upload_csv").upload("core.csv", DEMO_CSV, "text/csv").run()
    at.button(key="load_upload").click().run()
    assert not at.exception and len(at.session_state["workspace"].records.records) == 4
    at.button(key="extract_demo").click().run()
    assert not at.exception and at.session_state["workspace"].extraction.coverage.success == 4
    at.selectbox(key="evidence_category").set_value("service").run()
    assert any(metric.label == "Matching distinct records" and metric.value == "2" for metric in at.metric)
    at.selectbox(key="method").set_value("b").run()
    at.button(key="ask").click().run()
    answer = at.session_state["workspace"].answer
    assert not at.exception and answer.status == "ok" and answer.numeric_claims[0].value == 2 / 3
    assert [event.tool_name for event in answer.tool_trace] == ["aggregate_aspects"]
    at.button(key="compare").click().run()
    assert not at.exception and set(at.session_state["workspace"].comparison) == {"a", "b", "c"}
    assert at.session_state["workspace"].comparison["c"].usage["decision_rounds"] == 2
    refreshed = AppTest.from_file(APP)
    refreshed.query_params["session"] = token
    refreshed.run()
    assert not refreshed.exception and refreshed.session_state["workspace"].answer.numeric_claims[0].value == 2 / 3
    assert set(refreshed.session_state["workspace"].comparison) == {"a", "b", "c"}
    refreshed.button(key="clear_workspace").click().run()
    assert not refreshed.exception and refreshed.session_state["workspace"].records is None


def test_unrecognized_upload_does_not_claim_mock_extraction(tmp_path, monkeypatch):
    monkeypatch.setenv("ABSA_UI_SESSION_DIR", str(tmp_path))
    at = AppTest.from_file(APP).run()
    at.radio(key="source_mode").set_value("Upload CSV").run()
    at.file_uploader(key="upload_csv").upload("other.csv", b"text\nDifferent review.\n", "text/csv").run()
    at.button(key="load_upload").click().run()
    assert not at.exception and at.session_state["workspace"].records is not None
    assert at.session_state["workspace"].extraction is None
    at.button(key="ask").click().run()
    assert not at.exception and at.session_state["workspace"].answer is None
    assert any("only for the unchanged synthetic demo" in error.value for error in at.error)


def test_uploaded_validated_extraction_enables_deterministic_analysis(tmp_path, monkeypatch):
    monkeypatch.setenv("ABSA_UI_SESSION_DIR", str(tmp_path))
    at = AppTest.from_file(APP).run()
    at.radio(key="source_mode").set_value("Upload CSV").run()
    at.file_uploader(key="upload_csv").upload("other.csv", b"record_id,text\nU1,Bad service.\n", "text/csv").run()
    at.button(key="load_upload").click().run()
    records = at.session_state["workspace"].records
    dataset = ExtractionDataset(
        fingerprint=dataset_fingerprint(records), records=records.records,
        extractions=[ExtractionResult(record_id="U1", aspects=[{"category": "service", "sentiment": "negative", "evidence": ["Bad service"]}], status="ok")],
        provider_model="provided-offline", prompt_version="v1", schema_version="v1", coverage=Coverage(total=1, success=1),
    )
    at.file_uploader(key="upload_extraction").upload("extraction.json", dataset.model_dump_json().encode(), "application/json").run()
    at.button(key="load_extraction").click().run()
    assert not at.exception and at.session_state["workspace"].extraction_origin == "provided"
    at.selectbox(key="evidence_category").set_value("service").run()
    assert any(metric.label == "Matching distinct records" and metric.value == "1" for metric in at.metric)
    at.selectbox(key="method").set_value("b").run()
    at.button(key="ask").click().run()
    assert at.session_state["workspace"].answer is None
    assert any("offline MOCK question is available only" in error.value for error in at.error)
