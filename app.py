"""Streamlit UI for the honest synthetic MOCK demo and validated local data."""

from __future__ import annotations

import io
import json
import uuid

import pandas as pd
import streamlit as st

from src.absa_service import ExtractionService
from src.data_loader import dataset_fingerprint, load_csv, read_csv
from src.demo_mock import DEMO_FINGERPRINT, DEMO_QUESTION, mock_for_demo, run_demo_method
from src.schemas import AnswerPayload, Category, ExtractionDataset
from src.tools import AggregateArgs, AnalysisContext, EvidenceArgs, FilterArgs, aggregate_aspects, filter_records, get_evidence
from src.ui_state import UIWorkspace, clear_workspace, load_workspace, new_session_token, save_workspace


st.set_page_config(page_title="Evidence-Grounded ABSA", layout="wide")
st.title("Evidence-Grounded Restaurant Review Analysis")
st.caption("Synthetic MOCK demo · no live model or formal research results")

token = st.query_params.get("session")
try:
    token_valid = bool(token) and str(uuid.UUID(token)) == token
except (TypeError, ValueError):
    token_valid = False
if not token_valid:
    token = new_session_token()
    st.query_params["session"] = token
if "workspace" not in st.session_state:
    try:
        st.session_state["workspace"] = load_workspace(token)
    except (OSError, ValueError):
        st.session_state["workspace"] = UIWorkspace()
        st.warning("Could not restore the local workspace. Load data again.")
workspace: UIWorkspace = st.session_state["workspace"]


def persist(updated: UIWorkspace) -> None:
    global workspace
    workspace = updated
    st.session_state["workspace"] = updated
    try:
        save_workspace(token, updated)
    except OSError:
        st.error("Local workspace could not be saved; browser refresh may lose this session.")


def is_demo() -> bool:
    return workspace.records is not None and dataset_fingerprint(workspace.records) == DEMO_FINGERPRINT


dataset_tab, analysis_tab, evidence_tab, ask_tab, comparison_tab, results_tab = st.tabs(
    ["Dataset", "Analysis", "Evidence", "Ask", "Comparison", "Cost / Trace / Results"]
)

with dataset_tab:
    st.subheader("Dataset")
    st.write("Upload at most 1 MB of UTF-8 CSV with a `text` column and optional `record_id`, or load the four synthetic examples.")
    mode = st.radio("Source", ["Built-in synthetic demo", "Upload CSV"], key="source_mode")
    if mode == "Built-in synthetic demo":
        if st.button("Load synthetic demo", key="load_demo"):
            records = load_csv("data/demo/core.csv")
            persist(UIWorkspace(source_label="Synthetic demo", records=records))
    else:
        uploaded = st.file_uploader("Review CSV", type="csv", key="upload_csv", max_upload_size=1)
        if st.button("Load uploaded CSV", key="load_upload"):
            if uploaded is None:
                st.error("Choose a CSV file first.")
            else:
                try:
                    raw = uploaded.getvalue()
                    if len(raw) > 1_000_000:
                        raise ValueError("CSV exceeds the 1 MB local limit")
                    records = read_csv(io.StringIO(raw.decode("utf-8-sig")))
                    persist(UIWorkspace(source_label=f"Uploaded: {uploaded.name}", records=records))
                except (UnicodeDecodeError, ValueError) as exc:
                    st.error(f"CSV rejected: {exc}")
    if workspace.records is not None:
        st.success(f"Loaded {len(workspace.records.records)} records from {workspace.source_label}.")
        st.dataframe([record.model_dump() for record in workspace.records.records], hide_index=True)
        st.caption("Uploaded reviews and derived state are kept only in ignored local outputs/ui_sessions until cleared.")
        if st.button("Clear local workspace", key="clear_workspace"):
            clear_workspace(token)
            workspace = UIWorkspace()
            st.session_state["workspace"] = workspace
            st.success("Local workspace cleared.")
    else:
        st.info("Load a dataset to begin.")

with analysis_tab:
    st.subheader("Extraction and deterministic analysis")
    if workspace.records is None:
        st.info("Load a dataset in the Dataset tab.")
    else:
        st.metric("Review records", len(workspace.records.records))
        if is_demo():
            if st.button("Run synthetic MOCK extraction", key="extract_demo"):
                client = mock_for_demo(workspace.records, method="extract")
                run = ExtractionService(client, provider_model="mock").extract(workspace.records)
                persist(workspace.model_copy(update={"extraction": run.dataset, "extraction_origin": "synthetic_mock", "extraction_requests": run.requests,
                                                     "answer": None, "comparison": {}}))
        else:
            st.info("MOCK extraction supports only the unchanged synthetic demo. Upload a validated ExtractionDataset JSON for deterministic analysis of other CSVs.")
        extraction_file = st.file_uploader("Validated extraction JSON (optional)", type="json", key="upload_extraction", max_upload_size=5)
        if st.button("Load extraction JSON", key="load_extraction"):
            if extraction_file is None:
                st.error("Choose an extraction JSON file first.")
            else:
                try:
                    raw = extraction_file.getvalue()
                    if len(raw) > 5_000_000:
                        raise ValueError("Extraction JSON exceeds the 5 MB local limit")
                    data = json.loads(raw)
                    dataset = ExtractionDataset.model_validate(data.get("dataset", data))
                    persist(UIWorkspace(source_label=workspace.source_label, records=workspace.records,
                                        extraction=dataset, extraction_origin="provided", extraction_requests=None))
                except (ValueError, UnicodeDecodeError, TypeError) as exc:
                    st.error(f"Extraction rejected: {exc}")
        if workspace.extraction is not None:
            coverage = workspace.extraction.coverage
            st.success(f"Extraction: {coverage.success}/{coverage.total} records; {len(coverage.failed_ids)} failed. Source model: {workspace.extraction.provider_model}.")
            context = AnalysisContext(workspace.extraction)
            aggregate = aggregate_aspects(context, AggregateArgs(categories=list(Category), metric="negative_rate"))
            rows = [{"aspect": stat.category.value, "mentions": stat.mention_count, "negative": stat.negative_count,
                     "neutral": stat.neutral_count, "conflict": stat.conflict_count, "negative_rate": stat.rate,
                     "denominator": stat.denominator} for stat in aggregate.stats]
            st.dataframe(rows, hide_index=True)
            st.bar_chart(pd.DataFrame(rows).set_index("aspect")[["negative"]])
            if aggregate.status == "partial":
                st.warning("Statistics are partial because extraction failed for some records.")

with evidence_tab:
    st.subheader("Source evidence")
    if workspace.extraction is None:
        st.info("Run or load extraction first.")
    else:
        category = st.selectbox("Aspect", [item.value for item in Category], key="evidence_category")
        sentiment = st.selectbox("Sentiment", ["negative", "positive", "neutral", "conflict"], key="evidence_sentiment")
        context = AnalysisContext(workspace.extraction)
        filtered = filter_records(context, FilterArgs(conditions=[{"category": category, "sentiment": sentiment}]))
        evidence = get_evidence(context, EvidenceArgs(record_ids=filtered.record_ids, categories=[category], sentiments=[sentiment], max_examples=10))
        st.metric("Matching distinct records", filtered.count)
        if filtered.status == "partial":
            st.warning("Selection is partial because some extractions failed.")
        for item in evidence.examples:
            with st.expander(item.record_id):
                st.write(item.text)
                st.json([aspect.model_dump(mode="json") for aspect in item.aspects])
        if not evidence.examples:
            st.info("No matching records in the validated extraction.")

with ask_tab:
    st.subheader("Ask the synthetic demo")
    question = st.text_input("Question", value=DEMO_QUESTION, key="question")
    method = st.selectbox("Method", ["a", "b", "c"], key="method")
    if st.button("Ask", key="ask"):
        if workspace.records is None or not is_demo() or question != DEMO_QUESTION:
            st.error("The offline MOCK question is available only for the unchanged synthetic demo and exact displayed wording.")
        elif method in {"b", "c"} and workspace.extraction_origin != "synthetic_mock":
            st.error("Run synthetic MOCK extraction first for B/C.")
        else:
            try:
                answer, _ = run_demo_method(workspace.records, method=method, question=question,
                                             extraction_dataset=workspace.extraction if method in {"b", "c"} else None)
                persist(workspace.model_copy(update={"answer": answer}))
            except ValueError as exc:
                st.error(str(exc))
    if workspace.answer is not None:
        st.write(workspace.answer.answer_text or workspace.answer.error_code)
        st.write(f"Status: {workspace.answer.status.upper()} · Method {workspace.answer.method.upper()} · MOCK")
        st.json([claim.model_dump(mode="json") for claim in workspace.answer.numeric_claims])
        if workspace.answer.denominator_explanation:
            st.caption(workspace.answer.denominator_explanation)
        for citation in workspace.answer.citations:
            st.markdown(f"> {citation.record_id}: {citation.quote}")

with comparison_tab:
    st.subheader("A/B/C comparison on the same four reviews")
    if st.button("Compare A/B/C", key="compare"):
        if workspace.records is None or workspace.extraction_origin != "synthetic_mock" or not is_demo():
            st.error("Load and extract the synthetic demo first.")
        else:
            answers = {}
            for selected_method in ("a", "b", "c"):
                answer, _ = run_demo_method(workspace.records, method=selected_method, question=DEMO_QUESTION,
                                             extraction_dataset=workspace.extraction if selected_method in {"b", "c"} else None)
                answers[selected_method] = answer
            persist(workspace.model_copy(update={"comparison": answers}))
    if workspace.comparison:
        rows = []
        for selected_method in ("a", "b", "c"):
            answer: AnswerPayload = workspace.comparison[selected_method]
            rows.append({"method": selected_method.upper(), "status": answer.status,
                         "rate": answer.numeric_claims[0].value if answer.numeric_claims else None,
                         "query_requests": answer.usage.get("api_requests"),
                         "analysis_tools": answer.usage.get("analysis_tool_calls", 0)})
        st.dataframe(rows, hide_index=True)
        st.caption(f"MOCK only. B/C reused one extraction artifact ({workspace.extraction_requests} extraction requests); table shows later query requests. No accuracy claim.")

with results_tab:
    st.subheader("Cost, trace and results")
    st.info("No live model or formal experiment results are available. All displayed answers and costs are synthetic MOCK traces.")
    if workspace.answer is not None:
        st.write("Latest answer usage")
        st.json(workspace.answer.usage)
        st.write("Latest tool trace")
        st.json([event.model_dump(mode="json") for event in workspace.answer.tool_trace])
    if workspace.comparison:
        st.write("A/B/C response status")
        st.json({method: {"status": answer.status, "usage": answer.usage} for method, answer in workspace.comparison.items()})
