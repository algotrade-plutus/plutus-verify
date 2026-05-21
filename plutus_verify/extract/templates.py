"""Per-call templates for the decomposed form-filling extractor (Iteration 4).

Each call has:
- A small system prompt (role + JSON-only + fill-the-blanks rule).
- A user prompt template containing the shape with ``<BRACKETED_PLACEHOLDERS>``
  for what the LLM should write. Field names in the prompt are fixed; the LLM
  cannot rename them. Enum values are shown inline as ``<"a" | "b" | "c">``;
  the LLM picks one verbatim.

Returned JSON is small (200 B – 2 KB) so retries are cheap.
"""
from __future__ import annotations

# ---------- Shared system prompt ----------

SYSTEM_FILL = (
    "You fill in a small JSON template based on a README excerpt.\n"
    "Output JSON only — no prose, no code fences, no comments.\n"
    "The template uses <BRACKETED_PLACEHOLDERS> showing what to fill in.\n"
    "Replace each bracket with the appropriate value. Field names in the "
    "template are FIXED — do not rename them. Enum values shown as "
    '<"a" | "b" | "c"> mean: pick exactly one of those strings, verbatim. '
    "Use null for fields you genuinely cannot determine from the README."
)


# ---------- Call 1: Repo metadata ----------

CALL1_REPO_USER = """Fill in this repo-metadata template based on the README.

Template:
{{
  "name": <PROJECT_NAME_FROM_TITLE_OR_FIRST_HEADING>,
  "primary_language": <"python" | "julia" | "r" | "other">,
  "env_setup": {{
    "kind": <"requirements_txt" | "environment_yml" | "pipfile" | "dockerfile" | "none">,
    "path": <FILE_PATH_OR_NULL>,
    "python_version": <VERSION_STRING_OR_NULL>
  }},
  "secrets_required": [
    {{"key": <ENV_VAR_NAME>, "purpose": <SHORT_DESCRIPTION>}}
  ]
}}

Rules:
- If the repo has no secrets (no .env file mentioned, no DB credentials), return secrets_required: [].
- "kind": "requirements_txt" if requirements.txt is mentioned; "environment_yml" for conda; "dockerfile" if a Dockerfile is the env spec; "none" if none described.

README:
---
{readme}
---

Return the filled-in JSON object only."""


# ---------- Call 2: Nine-step presence ----------

CALL2_NINE_STEP_USER = """For each of the 7 PLUTUS standard steps, decide whether the README describes that step and what the section heading is.

Template:
{{
  "step_1_hypothesis":      {{"present": <true|false>, "section_heading": <STRING_OR_NULL>}},
  "step_2_data_collection": {{"present": <true|false>, "section_heading": <STRING_OR_NULL>}},
  "step_3_data_processing": {{"present": <true|false>, "section_heading": <STRING_OR_NULL>}},
  "step_4_in_sample":       {{"present": <true|false>, "section_heading": <STRING_OR_NULL>}},
  "step_5_optimization":    {{"present": <true|false>, "section_heading": <STRING_OR_NULL>}},
  "step_6_out_of_sample":   {{"present": <true|false>, "section_heading": <STRING_OR_NULL>}},
  "step_7_paper_trading":   {{"present": <true|false>, "section_heading": <STRING_OR_NULL>}}
}}

Rules:
- "present" = true only if there's an explicit section or paragraph describing this step's purpose, command, or result.
- "section_heading" = the exact heading text from the README (e.g., "In-sample Backtesting"), or null if present is false.

README:
---
{readme}
---

Return the filled-in JSON object only."""


# ---------- Call 3: Steps (batched) ----------

CALL3_STEPS_USER = """For each PLUTUS step marked present below, produce one Step entry. Mirror the Step template EXACTLY.

Present steps (from prior call):
{present_steps}

Step template (use this shape for every entry in the array):
{{
  "id": <SNAKE_CASE_NAME>,
  "nine_step": <ONE_OF_PRESENT_STEP_KEYS_ABOVE>,
  "required": <true|false>,
  "verification_mode": <"execute" | "artifact_check">,
  "command": <SHELL_COMMAND_OR_NULL>,
  "network": <"none" | "bridge" | "host">,
  "config_files": [<PATH>...],
  "produces": [<PATH>...],
  "alternatives": [
    {{"label": <SHORT_LABEL>, "kind": <"manual_download" | "command">,
     "url": <URL_OR_NULL>, "command": <SHELL_COMMAND_OR_NULL>,
     "needs_secrets": [<ENV_VAR_NAME>...]}}
  ]
}}

Rules:
- Only emit Step entries for present, EXECUTABLE steps (step_1_hypothesis is descriptive, never executable; step_7_paper_trading rarely is).
- COMMAND PROVENANCE: a step's "command" MUST come from an explicit shell command shown in a code block in the README's implementation/usage section (e.g., ```bash\npython foo.py\n```). NEVER invent a command from a filename you happen to see in the repo. If a step is described only in prose (e.g., "Data Processing: we resample to OHLC and drop NaN rows" with no `python ...` command), this means the work is internal to another step (typically the backtest) and is NOT independently executable. In that case, either omit the step entirely OR emit it with `command: null` and `required: false`.
- "verification_mode": use "artifact_check" for step_5_optimization when the README says the optimized parameter file is shipped in the repo (skip re-running the optimization). For all other steps use "execute".
- "command": null for steps in artifact_check mode. null for data_collection steps whose only path is a manual download.
- "network": "none" by default. "bridge" only for steps that genuinely need internet (data download, API fetch).
- "alternatives": include only when the step has multiple ways to run (e.g., data collection via manual Google Drive download AND via a credentialed script). Otherwise return an empty array.
- MULTIPLE INVOCATIONS: if a step type requires several distinct commands to produce the full set of reported results (e.g., the README reports OOS metrics for 2021, 2022, AND 2023, each produced by a different `--data_file` argument), emit ONE Step entry per invocation. Each gets a unique "id" (e.g., `out_of_sample_2021`, `out_of_sample_2022`, `out_of_sample_2023`), the same "nine_step" key, and its own "command". The next call (expected_results) will then associate the right metrics with each step_id. If the README has only one invocation per step type, emit a single entry as usual.

README:
---
{readme}
---

Return a JSON ARRAY of Step entries, one per present executable step: [<entry>, <entry>, ...]."""


# ---------- Call 4: Expected results / metrics (batched) ----------

CALL4_RESULTS_USER = """For each step ID below that reports results (numbers in tables, charts, or JSON file values), produce one ExpectedResult entry.

Step IDs to consider (from prior call):
{step_ids}

ExpectedResult template:
{{
  "step_id": <ONE_OF_THE_STEP_IDS_ABOVE>,
  "metrics": [
    {{
      "name": <METRIC_NAME_MATCHING_THE_README>,
      "value": <NUMBER_FROM_THE_README>,
      "locate": {{
        "kind": <"stdout_table" | "json_file" | "file_regex">,
        "row": <ROW_LABEL_FOR_STDOUT_TABLE_OR_NULL>,
        "col": <COLUMN_INDEX_FOR_STDOUT_TABLE_OR_NULL>,
        "path": <FILE_PATH_FOR_JSON_FILE_OR_FILE_REGEX_OR_NULL>,
        "jsonpath": <JSONPATH_STRING_OR_NULL>,
        "pattern": <REGEX_PATTERN_OR_NULL>
      }},
      "tolerance": {{
        "kind": <"relative" | "absolute" | "exact">,
        "value": <NUMBER>
      }}
    }}
  ],
  "charts": [
    {{"name": <CHART_NAME>, "produced_path": <PATH_RELATIVE_TO_REPO_ROOT>}}
  ]
}}

Rules:
- locate.kind = "stdout_table" for metrics printed by the script to stdout (set row to the label, col to the column index 1-based; leave path/jsonpath/pattern null).
- locate.kind = "json_file" when the value is read from a JSON file (set path and jsonpath; jsonpath like "$.step"; leave row/col/pattern null).
- locate.kind = "file_regex" only if neither stdout_table nor json_file fits (set path and pattern).
- For stdout_table metrics, "name" should match "row" exactly (the same label the script prints).
- tolerance: ratios -> {{"kind":"relative","value":0.05}}; percentages/drawdowns -> {{"kind":"absolute","value":0.02}} (or up to 1.0); integers -> {{"kind":"exact","value":0}}.
- Capture EVERY metric the README's tables list for each step. If the README's in-sample section reports 6 metrics, the in_sample entry should have 6 metrics.
- Skip steps that report no results (e.g., paper_trading rarely has results).

README:
---
{readme}
---

Return a JSON ARRAY of ExpectedResult entries: [<entry>, <entry>, ...]. Empty array if none."""


# ---------- Per-call retry suffix ----------

RETRY_SUFFIX = """

Previous attempt failed validation: {error}

Re-read the template and rules above. Output ONLY the corrected JSON."""
