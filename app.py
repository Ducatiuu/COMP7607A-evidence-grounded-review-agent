"""Streamlit UI for the honest synthetic MOCK demo and validated local data."""

from __future__ import annotations

import io
import json
import uuid

import pandas as pd
import streamlit as st

from src.absa_service import ExtractionService
from src.data_loader import dataset_fingerprint, load_csv, read_csv
from src.demo_mock import DEMO_FINGERPRINT, PRESENTATION_FINGERPRINT, DEMO_MISSING_DATE_QUESTION, DEMO_QUESTION, mock_for_demo, run_demo_method
from src.schemas import AnswerPayload, Category, ExtractionDataset
from src.tools import AggregateArgs, AnalysisContext, EvidenceArgs, FilterArgs, aggregate_aspects, filter_records, get_evidence
from src.ui_live import MAX_RECORDS, run_live_answer, run_live_extraction
from src.ui_state import UIWorkspace, clear_workspace, load_workspace, new_session_token, save_workspace


st.set_page_config(page_title="Evidence-Grounded ABSA", layout="wide")
st.title("Evidence-Grounded Restaurant Review Analysis")
st.caption("Synthetic MOCK demo or guarded DeepSeek analysis · no formal research results")

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
    return workspace.records is not None and dataset_fingerprint(workspace.records) in {DEMO_FINGERPRINT, PRESENTATION_FINGERPRINT}


dataset_tab, analysis_tab, evidence_tab, ask_tab, comparison_tab, results_tab = st.tabs(
    ["Dataset", "Analysis", "Evidence", "Ask", "Comparison", "Cost / Trace / Results"]
)

with dataset_tab:
    st.subheader("Dataset")
    st.write("Upload at most 1 MB of UTF-8 CSV with a `text` column and optional `record_id`, or load a synthetic fixture.")
    mode = st.radio("Source", ["Built-in synthetic demo", "60-record simulated demo", "Upload CSV"], key="source_mode")
    if mode in {"Built-in synthetic demo", "60-record simulated demo"}:
        if st.button("Load synthetic demo", key="load_demo"):
            path = "data/demo/core.csv" if mode == "Built-in synthetic demo" else "data/demo/presentation.csv"
            records = load_csv(path)
            persist(UIWorkspace(source_label="Synthetic Proposal example" if mode == "Built-in synthetic demo" else "60 simulated entries", records=records))
    else:
        uploaded = st.file_uploader("Review CSV", type="csv", key="upload_csv", max_upload_size=1)
        text_column = st.text_input("Review text column", value="text", key="upload_text_column")
        id_column = st.text_input("Optional ID column", value="record_id", key="upload_id_column")
        if st.button("Load uploaded CSV", key="load_upload"):
            if uploaded is None:
                st.error("Choose a CSV file first.")
            else:
                try:
                    raw = uploaded.getvalue()
                    if len(raw) > 1_000_000:
                        raise ValueError("CSV exceeds the 1 MB local limit")
                    records = read_csv(io.StringIO(raw.decode("utf-8-sig")),
                                       text_column=text_column, id_column=id_column)
                    persist(UIWorkspace(source_label=f"Uploaded: {uploaded.name}", records=records))
                except (UnicodeDecodeError, ValueError) as exc:
                    st.error(f"CSV rejected: {exc}")
    if workspace.records is not None:
        st.success(f"Loaded {len(workspace.records.records)} records from {workspace.source_label}.")
        st.dataframe([record.model_dump() for record in workspace.records.records], hide_index=True)
        st.caption("Uploaded reviews and derived state are kept in ignored local outputs/ui_sessions; live traces are saved separately in outputs/ui_live_runs.")
        if st.button("Clear local workspace", key="clear_workspace"):
            clear_workspace(token)
            workspace = UIWorkspace()
            st.session_state["workspace"] = workspace
            st.success("Local workspace cleared. Saved live run traces remain under outputs/ui_live_runs.")
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
            st.info("Run live DeepSeek extraction for uploaded CSV, or load a matching ExtractionDataset JSON for deterministic analysis.")
        if st.button("Run live DeepSeek extraction", key="extract_live"):
            if len(workspace.records.records) > MAX_RECORDS:
                st.error(f"Live analysis accepts up to {MAX_RECORDS} reviews at a time.")
            else:
                try:
                    dataset, summary = run_live_extraction(workspace.records, source_label=workspace.source_label)
                    persist(workspace.model_copy(update={"extraction": dataset,
                                                 "extraction_origin": "live_deepseek",
                                                 "extraction_requests": summary["requests"],
                                                 "answer": None, "answer_origin": None,
                                                 "live_run_summary": summary, "comparison": {}}))
                except (ValueError, RuntimeError, OSError) as exc:
                    st.error(f"Live extraction stopped: {type(exc).__name__}. Check the key, current price verification and run limits.")
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
            highest = max(stat.negative_count for stat in aggregate.stats)
            leaders = [stat.category.value for stat in aggregate.stats if stat.negative_count == highest]
            st.write(f"Highest observed negative record count: {', '.join(leaders)} ({highest}).")
            st.caption("Counts are distinct records in this dataset, not customers or financial impact.")
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
        st.subheader("Combined aspect selection")
        left_category = st.selectbox("First aspect", [item.value for item in Category], key="and_category_1")
        left_sentiment = st.selectbox("First sentiment", ["positive", "negative", "neutral", "conflict"], key="and_sentiment_1")
        right_category = st.selectbox("Second aspect", [item.value for item in Category], index=1, key="and_category_2")
        right_sentiment = st.selectbox("Second sentiment", ["negative", "positive", "neutral", "conflict"], key="and_sentiment_2")
        combined = filter_records(context, FilterArgs(conditions=[{"category": left_category, "sentiment": left_sentiment},
                                                               {"category": right_category, "sentiment": right_sentiment}], operator="AND"))
        st.metric("AND matching records", combined.count)
        if combined.status == "partial":
            st.warning("Combined selection is partial because some extractions failed.")
        if combined.record_ids:
            selected = get_evidence(context, EvidenceArgs(record_ids=combined.record_ids, max_examples=10))
            for item in selected.examples:
                with st.expander(f"AND {item.record_id}"):
                    st.write(item.text)
                    st.json([aspect.model_dump(mode="json") for aspect in item.aspects])
        else:
            st.info("No records match both aspect conditions.")

with ask_tab:
    st.subheader("Ask the synthetic demo")
    question = st.text_input("Question", value=DEMO_QUESTION, key="question")
    st.caption(f"Available MOCK prompts: {DEMO_QUESTION} | {DEMO_MISSING_DATE_QUESTION}")
    method = st.selectbox("Method", ["a", "b", "c"], key="method")
    if st.button("Ask", key="ask"):
        if workspace.records is None or not is_demo() or question not in {DEMO_QUESTION, DEMO_MISSING_DATE_QUESTION}:
            st.error("Offline MOCK questions are available only for the unchanged synthetic fixtures and exact displayed wording.")
        elif method in {"b", "c"} and workspace.extraction_origin != "synthetic_mock":
            st.error("Run synthetic MOCK extraction first for B/C.")
        else:
            try:
                answer, _ = run_demo_method(workspace.records, method=method, question=question,
                                             extraction_dataset=workspace.extraction if method in {"b", "c"} else None)
                persist(workspace.model_copy(update={"answer": answer, "answer_origin": "synthetic_mock"}))
            except ValueError as exc:
                st.error(str(exc))
    st.subheader("Ask live DeepSeek about loaded reviews")
    live_question = st.text_input("Live question", key="live_question")
    live_method = st.selectbox("Live method", ["a", "b", "c"], key="live_method")
    if st.button("Ask live", key="ask_live"):
        if workspace.records is None:
            st.error("Load a CSV first.")
        elif live_method in {"b", "c"} and workspace.extraction_origin != "live_deepseek":
            st.error("Run live DeepSeek extraction on this CSV before asking with B or C.")
        else:
            try:
                answer, summary = run_live_answer(workspace.records, question=live_question,
                                                  method=live_method, extraction=workspace.extraction,
                                                  source_label=workspace.source_label)
                persist(workspace.model_copy(update={"answer": answer,
                                             "answer_origin": "live_deepseek",
                                             "live_run_summary": summary}))
            except (ValueError, RuntimeError, OSError) as exc:
                st.error(f"Live answer stopped: {type(exc).__name__}. Check the key, current price verification and run limits.")

    if workspace.answer is not None:
        st.write(workspace.answer.answer_text or workspace.answer.error_code)
        st.write(f"Status: {workspace.answer.status.upper()} · Method {workspace.answer.method.upper()} · {('LIVE DeepSeek' if workspace.answer_origin == 'live_deepseek' else 'MOCK')}")
        st.json([claim.model_dump(mode="json") for claim in workspace.answer.numeric_claims])
        if workspace.answer.denominator_explanation:
            st.caption(workspace.answer.denominator_explanation)
        for citation in workspace.answer.citations:
            st.markdown(f"> {citation.record_id}: {citation.quote}")

with comparison_tab:
    st.subheader("A/B/C comparison on the same records")
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
        st.caption(f"MOCK only. B/C reused one extraction artifact ({workspace.extraction_requests} extraction requests); table shows later query requests. No model accuracy claim.")

with results_tab:
    st.subheader("Cost, trace and results")
    st.info("Local live runs are development analysis, not formal experiment scores. Source and numeric checks do not judge semantic correctness.")
    if workspace.live_run_summary is not None:
        st.write("Latest live run and verification scope")
        st.json(workspace.live_run_summary)
    if workspace.answer is not None:
        st.write("Latest answer usage")
        st.json(workspace.answer.usage)
        st.write("Latest tool trace")
        st.json([event.model_dump(mode="json") for event in workspace.answer.tool_trace])
    if workspace.comparison:
        st.write("A/B/C response status")
        st.json({method: {"status": answer.status, "usage": answer.usage} for method, answer in workspace.comparison.items()})
