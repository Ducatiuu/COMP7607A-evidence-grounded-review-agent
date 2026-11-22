# Four-minute synthetic walkthrough

**Mode:** SIMULATED data and predefined MOCK model responses. This walkthrough demonstrates interface and tool behavior only. It does not present model accuracy, actual API costs or formal experimental results.

| Time | Action | Expected visible evidence |
|---|---|---|
| 0:00–0:35 | Start `python -m streamlit run app.py`, choose **60-record simulated demo**, and load it. | Dataset tab shows 60 entries and their original synthetic text. |
| 0:35–1:20 | Run **synthetic MOCK extraction**; inspect the Analysis table and bar chart. | Coverage 60/60; service has the largest observed negative record count (24), with 48 mentions and rate 0.5. Counts describe records, not customers or impact. |
| 1:20–2:05 | In Evidence, select service/negative and expand S01. Then inspect the default food-positive AND service-negative selection. | S01 praises noodles while reporting a forgotten order; the AND selection contains six records. Source spans and IDs are visible. |
| 2:05–2:40 | Ask “What is the negative service rate?” using Method B or C. | The structured answer states 24/48 = 50%, denominator explanation and tool trace. |
| 2:40–3:10 | Replace the question with “Did negative service reviews improve over the last month?” and Ask. | `insufficient_info` because no date metadata exists. No trend is invented. |
| 3:10–4:00 | Restore the rate question, click **Compare A/B/C**, then show Cost / Trace / Results. | Same 60 synthetic records; B/C share one extraction artifact. All method outputs and usage are labeled MOCK. The results tab says no live/formal results exist. |

This script is ready for a local rehearsal. A live provider demonstration, genuine saved fallback and final results page require separate model approval, real pilot and reviewed experiment data. Do not stage a baseline failure or copy synthetic values into the research report.
