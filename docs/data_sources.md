# SemEval-2014 Task 4 data handling

The [official task page](https://alt.qcri.org/semeval2014/task4/index.php?id=data-and-tools) links restaurant training and phased test resources through META-SHARE. The [task paper](https://alt.qcri.org/semeval2014/cdrom/pdf/SemEval004.pdf) describes a non-commercial, no-redistribution license (Section 3.3). This repository contains no SemEval review text or gold labels. Obtain the authorized restaurant XML files under the applicable terms, keep them under ignored `data/raw/`, and record the actual source URL/accession when running the local preparation script. Do not fetch an unverified third-party mirror into public history.

The parser expects `<sentences><sentence id="..."><text>...</text><aspectCategories><aspectCategory category="..." polarity="..."/></aspectCategories></sentence></sentences>`. It rejects DTDs, missing text/IDs, invalid labels, duplicate categories within one sentence, and a file without any category-polarity labels. Source bytes are hashed before parsing.

```powershell
.\.venv\Scripts\python -m scripts.prepare_semeval --train data/raw/Restaurants_Train_v2.xml --test data/raw/Restaurants_Test_Gold.xml --train-source ACTUAL_TRAIN_SOURCE --test-source ACTUAL_TEST_SOURCE
.\.venv\Scripts\python -m scripts.build_questions
```

Replace filenames and source identifiers with the actual licensed files. Preparation writes `data/processed/candidate_split.json`, `dev.csv`, `test.csv`, and separate gold files under `data/gold/`. The next command writes candidate questions under `data/processed/` and gold references under `data/gold/`. All these paths are Git ignored. Outputs are explicitly `CANDIDATE_UNREVIEWED`. Seed 42 selects exactly 150 dev and 600 test sentences, partitioned into 20 packs of 30, when sufficient distinct records exist. Exact duplicate texts retain the first source occurrence in a documented deterministic rule; conflicting-label duplicate groups are excluded from the candidate pool, and cross-split text overlap is excluded from dev. The audit manifest lists source URLs, file hashes, all exclusions and selected-label distributions. The original test source is not used for prompt tuning.

No actual XML or formal test question/reference review was available in this workspace on 2026-11-22. The script and synthetic tests do not establish a frozen benchmark or permission to redistribute its content.
