"""Agentic QC review of genome sequencing metrics (demo).

An LLM is given tools to inspect a QC table, compare samples with thresholds
and request reruns. A human must approve every rerun. The model never invents
numbers: it can only quote what the tools return.

Usage:
    export ANTHROPIC_API_KEY=...
    python qc_agent.py --qc data/qc_demo.tsv            # asks you to approve reruns
    python qc_agent.py --qc data/qc_demo.tsv --auto-approve
"""
import argparse
import csv
import json
from pathlib import Path

DEFAULT_MODEL = "claude-sonnet-5-5"
MAX_TURNS = 15

# Illustrative thresholds only. Set these from your own pipeline's validation.
THRESHOLDS = {
    "mean_coverage_min": 15.0,
    "pct_mapped_min": 85.0,
    "pct_genome_10x_min": 80.0,
    "freemix_max": 0.03,
}

SYSTEM = """You are a careful QC reviewer for whole-genome sequencing of Anopheles samples.
Rules:
- Use the tools to get every number. Never guess or recall metrics.
- Classify each sample as PASS, BORDERLINE (within 10% of a threshold) or FAIL, quoting the metric values.
- Request a rerun only when a rerun could plausibly help (e.g. low coverage or mapping from a
  failed run). Contamination is not fixed by rerunning the pipeline: recommend exclusion or
  re-extraction instead.
- Finish with a short markdown report: a table (sample, status, reason, action) and one
  paragraph on anything a human should double-check."""

TOOLS = [
    {
        "name": "list_samples",
        "description": "List all sample IDs in the QC table.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_thresholds",
        "description": "Return the QC thresholds in use.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_metrics",
        "description": "Return QC metrics for one sample.",
        "input_schema": {
            "type": "object",
            "properties": {"sample_id": {"type": "string"}},
            "required": ["sample_id"],
        },
    },
    {
        "name": "request_rerun",
        "description": "Ask a human to approve re-sequencing or re-processing of a sample.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sample_id": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["sample_id", "reason"],
        },
    },
]


def load_qc(path):
    """Read a tab-separated QC table into {sample_id: {metric: value}}."""
    qc = {}
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            sid = row.pop("sample_id")
            qc[sid] = {k: (float(v) if _is_number(v) else v) for k, v in row.items()}
    return qc


def _is_number(value):
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


class Toolbox:
    """Executes the tools the model asks for. All side effects live here."""

    def __init__(self, qc, thresholds=None, approve_fn=None):
        self.qc = qc
        self.thresholds = thresholds or THRESHOLDS
        self.approve_fn = approve_fn or (lambda sid, reason: False)
        self.rerun_log = []

    def call(self, name, args):
        try:
            if name == "list_samples":
                return json.dumps(sorted(self.qc))
            if name == "get_thresholds":
                return json.dumps(self.thresholds)
            if name == "get_metrics":
                sid = args["sample_id"]
                if sid not in self.qc:
                    return json.dumps({"error": f"unknown sample {sid}"})
                return json.dumps({"sample_id": sid, **self.qc[sid]})
            if name == "request_rerun":
                return self._rerun(args["sample_id"], args["reason"])
            return json.dumps({"error": f"unknown tool {name}"})
        except KeyError as exc:
            return json.dumps({"error": f"missing argument {exc}"})

    def _rerun(self, sid, reason):
        if sid not in self.qc:
            return json.dumps({"error": f"unknown sample {sid}"})
        approved = bool(self.approve_fn(sid, reason))
        self.rerun_log.append({"sample_id": sid, "reason": reason, "approved": approved})
        if not approved:
            return json.dumps({"status": "declined by human reviewer"})
        # Demo stub: in real use, trigger Snakemake/Nextflow or a ticket here.
        return json.dumps({"status": "rerun queued (demo stub, nothing executed)"})


def run_agent(client, toolbox, model=DEFAULT_MODEL, max_turns=MAX_TURNS):
    """Loop: model decides -> tools run -> results go back, until the model stops."""
    messages = [{"role": "user", "content": "Review every sample in the QC table and report."}]
    for _ in range(max_turns):
        resp = client.messages.create(
            model=model, max_tokens=2000, system=SYSTEM, tools=TOOLS, messages=messages
        )
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason != "tool_use":
            return "".join(b.text for b in resp.content if b.type == "text")
        results = [
            {
                "type": "tool_result",
                "tool_use_id": b.id,
                "content": toolbox.call(b.name, b.input),
            }
            for b in resp.content
            if b.type == "tool_use"
        ]
        messages.append({"role": "user", "content": results})
    raise RuntimeError(f"Agent did not finish within {max_turns} turns")


def _ask_human(sid, reason):
    answer = input(f"\nRerun {sid}? Reason: {reason}\nApprove [y/N]: ")
    return answer.strip().lower() == "y"


def main():
    import anthropic  # imported here so tests can run without the package

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qc", required=True, help="tab-separated QC table")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--auto-approve", action="store_true")
    parser.add_argument("--outdir", default="qc_output")
    args = parser.parse_args()

    approve = (lambda sid, reason: True) if args.auto_approve else _ask_human
    toolbox = Toolbox(load_qc(args.qc), approve_fn=approve)
    report = run_agent(anthropic.Anthropic(), toolbox, model=args.model)

    out = Path(args.outdir)
    out.mkdir(exist_ok=True)
    (out / "qc_report.md").write_text(report)
    (out / "rerun_log.json").write_text(json.dumps(toolbox.rerun_log, indent=2))
    print(report)
    print(f"\nSaved to {out}/ (report and rerun log)")


if __name__ == "__main__":
    main()
