# AgenticQCreview

An **agentic reviewer for genome sequencing QC tables**. Claude LLM inspects a QC table through a small set of tools, classifies each sample as PASS, BORDERLINE or FAIL, and can **request a rerun, which a human must approve** before anything happens. It finishes with a short markdown report.

Originally built for whole-genome sequencing of *Anopheles* mosquito samples in a malaria genomic surveillance setting, but the pattern applies to any QC table with per-sample metrics.

## Why this tool, and why use an agent?

Routine QC review is repetitive but needs judgement: low coverage can be fixed by resequencing, whereas contamination cannot be fixed by rerunning a pipeline. 
The tool shows how an LLM can do the reading and reasoning while a person stays in charge of every action:

- **The model never sees numbers it did not fetch.** It has no QC data in its prompt. It must call tools (`get_metrics`, `get_thresholds`) and quote what they return, so every number in the report comes from your table.
- **A human approves every rerun.** The `request_rerun` tool asks you `Approve [y/N]` for each request. Declined requests are logged and reported back to the model.
- **Every action is logged.** All rerun requests, with the reason and your decision, are written to `rerun_log.json`.
- **The loop is bounded.** The agent stops with an error after 15 turns rather than running indefinitely.
- **All side effects live in one place** (the `Toolbox` class), which keeps the behaviour easy to test and review.

## How it works

1. `load_qc` reads a tab-separated QC table into memory.
2. The model is given four tools and a system prompt with the review rules:

| Tool | Purpose |
|---|---|
| `list_samples` | List every sample ID in the table |
| `get_thresholds` | Return the QC thresholds in use |
| `get_metrics` | Return the metrics for one sample |
| `request_rerun` | Ask a human to approve a rerun, with a reason |

3. The model decides which tools to call, in a loop, until it has reviewed every sample.
4. The final output is a markdown table (sample, status, reason, action) and a short paragraph on anything a human should double-check.

The system prompt tells the model that rerunning can help with low coverage or poor mapping but **not with contamination**, for which it should recommend exclusion or re-extraction.

## Setup

```bash
git clone https://github.com/sophiemoss/AgenticQCreview.git
cd AgenticQCreview
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...        # from the Claude Platform console
python -m unittest -v               # offline tests, no key or internet needed
```

## Usage

```bash
# Interactive: asks you to approve each resequencing request
python qc_agent.py --qc data/qc_Anopheles_demo_data.tsv --thresholds thresholds_example.tsv

# Demo only: approves every request automatically (skips the human check)
python qc_agent.py --qc data/qc_Anopheles_demo_data.tsv --auto-approve

# Your own data, with a chosen model and output folder
python qc_agent.py --qc your_qc.tsv --model <model-name> --outdir qc_output
```

| Option | Meaning |
|---|---|
| `--qc` | Tab-separated QC table (required) |
| `--model` | Claude model to use (default set in `qc_agent.py`) |
| `--auto-approve` | Approve every rerun without asking. Defeats the human-in-the-loop check, so use it for demos and tests only |
| `--outdir` | Output folder (default `qc_output`) |

**Outputs** (in `--outdir`):

- `qc_report.md`: the review table and notes for the human reviewer
- `rerun_log.json`: every rerun request, its reason and whether it was approved

### Input format

A tab-separated file with a `sample_id` column plus numeric metric columns. The demo uses:

| Column | Meaning |
|---|---|
| `sample_id` | Unique sample name |
| `species` | Species label (carried through, not thresholded) |
| `mean_coverage` | Mean sequencing depth |
| `pct_mapped` | Percentage of reads mapped |
| `pct_genome_10x` | Percentage of the genome covered at 10x or more |
| `freemix` | Contamination estimate |

### Thresholds

Thresholds are set in `qc_agent.py` (`THRESHOLDS`):

| Threshold | Demo value |
|---|---|
| `mean_coverage_min` | 15.0 |
| `pct_mapped_min` | 85.0 |
| `pct_genome_10x_min` | 80.0 |
| `freemix_max` | 0.03 |

**These values are illustrative.** 
Set them from your own pipeline's validation, and edit the `THRESHOLDS` dictionary to change them. 
A sample is BORDERLINE when it is within 10% of a threshold.

## Demo data

`data/qc_demo.tsv` is **simulated** (made by `make_demo_qc.py`), so it is safe to share. It has 12 samples with four deliberate problems, so you can check the review behaves sensibly:

| Sample | Planted problem |
|---|---|
| `DEMO003` | Low coverage (6.2x, 41% of genome at 10x) |
| `DEMO006` | Contamination (freemix 0.12) |
| `DEMO009` | Poor mapping (61.5%) with low coverage |
| `DEMO011` | Borderline coverage (14.8x, just under the threshold) |

A correct review should flag these four, suggest a rerun where one could help (DEMO003, and possibly DEMO009), and **not** suggest a rerun for the contaminated sample.

## Connecting it to your pipeline

The `request_rerun` tool is currently a **stub**: if you approve, it logs the request and returns `rerun queued (demo stub, nothing executed)`. **Nothing is run.** To use it for real, replace the body of `Toolbox._rerun` in `qc_agent.py` with a call to your workflow manager (Snakemake, Nextflow) or a ticketing system. Keep the human approval step in front of it.

## Tests

```bash
python -m unittest -v
```

The tests run without an API key by replacing the model with a scripted fake client. They check that:

- the tools return the right values and report errors for unknown samples and missing arguments
- a rerun is only queued when the human approves, and declined requests are logged
- the agent loop calls tools, feeds results back and returns the final report
- the loop stops with an error if the model never finishes (runaway protection)

These tests verify the **code around the model**. They do not measure how accurate the model's classifications are (see below).

## Limitations

- **Run-to-run variation.** Language models can answer differently on repeated runs. Check important calls against the underlying metrics, which the report quotes.
- **Column names matter.** The thresholds refer to the demo's column names. A table with different names needs matching changes to the thresholds and system prompt.
- **Demo thresholds and species-agnostic rules.** Real QC criteria vary by project, species and sequencing platform.
- **Data governance.** The model receives the QC metrics through an external API. **Do not send unpublished, restricted or identifiable data to an external API without checking your institution's data policy.** QC metrics are usually low risk, but sample names or metadata may not be.

## Files

| File | Purpose |
|---|---|
| `qc_agent.py` | The agent, tools, human approval step and command-line interface |
| `make_demo_qc.py` | Generates the simulated demo QC table |
| `data/qc_demo.tsv` | Simulated QC table with four planted problems |
| `test_offline.py` | Offline tests (no key needed) |
| `requirements.txt` | Python dependencies |
