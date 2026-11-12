"""Agentic QC review of genome sequencing metrics (demo).

A human sets the acceptable range for each sequencing parameter in a thresholds file.
An LLM agent then reviews a QC table with tools:
  * check_sample compares every parameter with the human-set range IN CODE, so the flags
    (PASS / BORDERLINE / FAIL, and which parameters are out of range) are exact
  * the model reasons about the flagged samples, looking at the pattern across parameters,
    and recommends an action
  * it may ask the human to approve RESEQUENCING; a "no" is a normal answer and the review
    carries on through every remaining sample
The model never invents numbers: it can only quote what the tools return. The script does not
finish until every sample has been checked and appears in the report. The authoritative flags,
the thresholds used and the human's decisions are added to the report by code.

Usage:
    export ANTHROPIC_API_KEY=...
    python qc_agent.py --qc data/qc_Anopheles_demo_data.tsv --thresholds thresholds_example.tsv
    python qc_agent.py --qc data/qc_Anopheles_demo_data.tsv --thresholds thresholds_example.tsv --auto-approve
"""
import argparse
import csv
import json
import math
import re
import sys
from pathlib import Path

DEFAULT_MODEL = "claude-sonnet-5-5"
MAX_TURNS = 15          # minimum; larger tables get more (see default_max_turns)
TURNS_PER_SAMPLE = 3
MAX_NUDGES = 3          # times the script sends the model back to finish skipped samples
DEFAULT_MARGIN = 0.10   # a value inside the range but within 10% of a limit is BORDERLINE

SYSTEM = """You are a careful QC reviewer for whole-genome sequencing of Anopheles samples.
A human has set the acceptable range for each sequencing parameter (see get_thresholds).

Workflow:
1. Call list_samples and get_thresholds.
2. For EVERY sample call check_sample. It compares each parameter with the human-set range in code and
   returns an overall status (PASS, BORDERLINE or FAIL) and which parameters are out of range or close to a
   limit. Use those flags exactly as returned. Never recompute or override them, and never quote a number
   that a tool did not return.
3. For every FAIL or BORDERLINE sample, reason about it. Look at the pattern across parameters, say what it
   plausibly means and what you cannot tell from the numbers, and recommend one action: accept with a note,
   resequence, reprocess/remap/realign existing data, re-extract, or exclude. Illustrative patterns, not rules:
   low depth together with low genome coverage suggests an under-sequenced library, where resequencing may help;
   low mapping with adequate depth may point to non-target DNA or the wrong reference, where checking species or
   remapping may help more than resequencing; high contamination is not fixed by resequencing, so recommend
   exclusion or re-extraction; depth that looks fine but low genome coverage suggests uneven coverage.
   Do not state a cause as fact if the numbers cannot show it.
4. Request RESEQUENCING (generating new sequence data) only when it could plausibly help. A human approves or
   declines each request. A decline is NOT an error and NOT the end of the review: record the decision and any
   note, do not ask again about that sample, and carry on with the remaining samples, asking the human again only
   for other samples where resequencing could plausibly help. For reprocessing, remapping or realigning, do not
   request resequencing: recommend it in the report.
5. Finish with a markdown report: a table covering EVERY sample (sample, status as returned by check_sample,
   parameters out of range with their values and limits, reasoning, action), then one short paragraph on anything
   a human should double-check. A PASS sample needs only a short line."""

TOOLS = [
    {
        "name": "list_samples",
        "description": "List all sample IDs in the QC table.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_thresholds",
        "description": "Return the human-set acceptable range for each sequencing parameter, and the margin "
                       "used for BORDERLINE.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_metrics",
        "description": "Return the raw QC metrics for one sample (no flags). Use check_sample to review a sample.",
        "input_schema": {
            "type": "object",
            "properties": {"sample_id": {"type": "string"}},
            "required": ["sample_id"],
        },
    },
    {
        "name": "check_sample",
        "description": "Compare every parameter of one sample with the human-set range. Returns the overall "
                       "status (PASS, BORDERLINE, FAIL), which parameters are out of range or missing, which are "
                       "close to a limit, and the values. Call this for every sample.",
        "input_schema": {
            "type": "object",
            "properties": {"sample_id": {"type": "string"}},
            "required": ["sample_id"],
        },
    },
    {
        "name": "request_rerun",
        "description": (
            "Ask a human to approve RESEQUENCING (generating new sequence data) for one sample. "
            "The human may decline, for example because resequencing would not help and the data "
            "only needs reprocessing, remapping or realigning. A decline is not an error and not "
            "the end of the review: carry on with the remaining samples. Each sample can be "
            "asked about once. Do not use this tool to suggest reprocessing; put that in the report."
        ),
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


# ----------------------------------------------------------------------------- inputs
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


def _is_real_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and not math.isnan(value)


def _bound(text, parameter, side):
    """Parse a min or max cell: blank means no limit. Accepts '60' or '60%'."""
    text = (text or "").strip().rstrip("%").strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        raise ValueError(f"{parameter}: {side} is '{text}', which is not a number") from None
    if math.isnan(value) or math.isinf(value):
        raise ValueError(f"{parameter}: {side} must be a finite number")
    return value


def load_thresholds(path):
    """Read the human-set ranges. TSV columns: parameter, min, max, (unit), (note).

    Lines starting with # and blank lines are ignored. Returns
    {parameter: {"min": float|None, "max": float|None, "unit": str, "note": str}}.
    Raises ValueError with a clear message for anything that would make a check meaningless.
    """
    with open(path, newline="", encoding="utf-8-sig") as fh:
        lines = [ln for ln in fh.read().splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        raise ValueError("the thresholds file has no rows")
    reader = csv.DictReader(lines, delimiter="\t")
    header = [h.strip() for h in (reader.fieldnames or [])]
    missing = [c for c in ("parameter", "min", "max") if c not in header]
    if missing:
        raise ValueError(f"the thresholds file needs columns parameter, min and max (missing: {', '.join(missing)})")
    out = {}
    for raw in reader:
        row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
        name = row["parameter"]
        if not name:
            continue
        if name in out:
            raise ValueError(f"{name}: listed more than once")
        lo, hi = _bound(row["min"], name, "min"), _bound(row["max"], name, "max")
        if lo is None and hi is None:
            raise ValueError(f"{name}: needs a min, a max or both (delete the row if there is no limit)")
        if lo is not None and hi is not None and lo > hi:
            raise ValueError(f"{name}: min ({lo:g}) is greater than max ({hi:g})")
        out[name] = {"min": lo, "max": hi, "unit": row.get("unit", ""), "note": row.get("note", "")}
    if not out:
        raise ValueError("the thresholds file has no parameters")
    return out


def validate_thresholds(thresholds, qc):
    """Fail loudly on a typo'd parameter. Returns the QC columns that have no threshold (not assessed)."""
    columns = {c for metrics in qc.values() for c in metrics}
    unknown = sorted(set(thresholds) - columns)
    if unknown:
        raise ValueError("these parameters are in the thresholds file but not in the QC table: "
                         + ", ".join(unknown) + ". QC columns are: " + ", ".join(sorted(columns)))
    return sorted(columns - set(thresholds))


# ----------------------------------------------------------------------------- the flagging (code, not model)
def check_metrics(sample_id, metrics, thresholds, margin=DEFAULT_MARGIN):
    """Compare one sample with the human-set ranges. A value exactly on a limit is acceptable.

    Status per parameter: ok, near_limit (inside the range but within `margin` of a limit),
    out_of_range, or missing. Overall: FAIL if anything is out of range or missing, else
    BORDERLINE if anything is near a limit, else PASS.
    """
    params = []
    for name, t in thresholds.items():
        value = metrics.get(name)
        entry = {"parameter": name, "min": t["min"], "max": t["max"], "unit": t["unit"],
                 "value": value if _is_real_number(value) else None}
        if not _is_real_number(value):
            entry.update(status="missing", detail="value is missing or not a number, so it cannot be judged")
        elif t["min"] is not None and value < t["min"]:
            entry.update(status="out_of_range", limit_type="min", limit=t["min"], **_deviation(value, t["min"]))
        elif t["max"] is not None and value > t["max"]:
            entry.update(status="out_of_range", limit_type="max", limit=t["max"], **_deviation(value, t["max"]))
        else:
            entry["status"] = "ok"
            for limit_type in ("min", "max"):
                b = t[limit_type]
                if b and margin and abs(value - b) <= margin * abs(b):
                    entry.update(status="near_limit", limit_type=limit_type, limit=b,
                                 detail=f"inside the range but within {margin:.0%} of the {limit_type}")
                    break
        params.append(entry)
    flagged = [p["parameter"] for p in params if p["status"] in ("out_of_range", "missing")]
    near = [p["parameter"] for p in params if p["status"] == "near_limit"]
    return {"sample_id": sample_id, "overall": "FAIL" if flagged else "BORDERLINE" if near else "PASS",
            "out_of_range_or_missing": flagged, "near_a_limit": near, "parameters": params,
            "other_metrics": {k: v for k, v in metrics.items() if k not in thresholds}}


def _deviation(value, bound):
    out = {"deviation": round(abs(value - bound), 6)}
    if bound:
        out["deviation_pct_of_limit"] = round(abs(value - bound) / abs(bound) * 100, 1)
    return out


# ----------------------------------------------------------------------------- tools
def _normalise_decision(result):
    """approve_fn may return True/False or (True/False, note). Always return (bool, str)."""
    if isinstance(result, tuple):
        return bool(result[0]), str(result[1] if len(result) > 1 else "").strip()
    return bool(result), ""


class Toolbox:
    """Executes the tools the model asks for. All side effects live here."""

    def __init__(self, qc, thresholds, approve_fn=None, margin=DEFAULT_MARGIN):
        self.qc = qc
        self.thresholds = thresholds
        self.margin = margin
        self.approve_fn = approve_fn or (lambda sid, reason: False)
        self.rerun_log = []
        self.reviewed = set()   # samples the model has run check_sample on
        self.decisions = {}     # sample_id -> (approved, note); each sample is asked about once

    def check(self, sid):
        return check_metrics(sid, self.qc[sid], self.thresholds, self.margin)

    def call(self, name, args):
        try:
            if name == "list_samples":
                return json.dumps(sorted(self.qc))
            if name == "get_thresholds":
                return json.dumps({"acceptable_ranges": self.thresholds, "borderline_margin": self.margin})
            if name == "get_metrics":
                sid = args["sample_id"]
                if sid not in self.qc:
                    return json.dumps({"error": f"unknown sample {sid}"})
                return json.dumps({"sample_id": sid, **self.qc[sid]})
            if name == "check_sample":
                sid = args["sample_id"]
                if sid not in self.qc:
                    return json.dumps({"error": f"unknown sample {sid}"})
                self.reviewed.add(sid)
                return json.dumps(self.check(sid))
            if name == "request_rerun":
                return self._rerun(args["sample_id"], args["reason"])
            return json.dumps({"error": f"unknown tool {name}"})
        except KeyError as exc:
            return json.dumps({"error": f"missing argument {exc}"})

    def _rerun(self, sid, reason):
        if sid not in self.qc:
            return json.dumps({"error": f"unknown sample {sid}"})
        if sid in self.decisions:   # never ask the human twice about one sample
            approved, note = self.decisions[sid]
            return json.dumps({
                "status": "already decided: " + ("approved" if approved else "declined by human reviewer"),
                "human_note": note,
                "instruction": "Do not ask again about this sample. Continue with the remaining samples.",
            })
        approved, note = _normalise_decision(self.approve_fn(sid, reason))
        self.decisions[sid] = (approved, note)
        self.rerun_log.append({"sample_id": sid, "reason": reason, "approved": approved, "human_note": note})
        if not approved:
            return json.dumps({
                "status": "declined by human reviewer: NOT resequencing this sample",
                "human_note": note,
                "instruction": (
                    "This is a normal decision, not an error, and it does not end the review. "
                    "Record it for this sample, mention reprocessing, remapping or realignment in the "
                    "report if the data may still need it (and the human's note, if any), do not "
                    "request resequencing for this sample again, and continue with the remaining samples."
                ),
            })
        # Demo stub: in real use, trigger Snakemake/Nextflow or a ticket here.
        return json.dumps({"status": "resequencing queued (demo stub, nothing executed)"})


# ----------------------------------------------------------------------------- the agent loop
def default_max_turns(n_samples):
    return max(MAX_TURNS, TURNS_PER_SAMPLE * n_samples + 10)


def _mentions(report, sid):
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(sid)}(?![A-Za-z0-9_])", report) is not None


def uncovered_samples(toolbox, report):
    """Samples never run through check_sample, or absent from the report."""
    missing = set(toolbox.qc) - toolbox.reviewed
    missing |= {sid for sid in toolbox.qc if not _mentions(report, sid)}
    return sorted(missing)


def run_agent(client, toolbox, model=DEFAULT_MODEL, max_turns=None):
    """Loop: model decides -> tools run -> results go back, until every sample is checked.

    If the model tries to finish early (for example straight after a declined request), it is
    sent back to finish the remaining samples. After MAX_NUDGES the report is returned with a
    visible warning listing anything still uncovered, so nothing is silently dropped.
    """
    if max_turns is None:
        max_turns = default_max_turns(len(toolbox.qc))
    messages = [{"role": "user", "content": "Review every sample in the QC table and report."}]
    nudges = 0
    for _ in range(max_turns):
        resp = client.messages.create(
            model=model, max_tokens=6000, system=SYSTEM, tools=TOOLS, messages=messages
        )
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason == "tool_use":
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
            continue
        report = "".join(b.text for b in resp.content if b.type == "text")
        missing = uncovered_samples(toolbox, report)
        if not missing:
            return report
        if nudges >= MAX_NUDGES:
            return report + (
                "\n\n**WARNING: this report does not cover every sample.** "
                f"Not checked or not in the report: {', '.join(missing)}. Review these by hand."
            )
        nudges += 1
        messages.append({"role": "user", "content": (
            "The review is not finished. These samples are missing: " + ", ".join(missing) + ". "
            "A declined resequencing request does not end the review. Use check_sample for any sample "
            "you have not yet checked, ask the human about resequencing only where it could help, "
            "then give the complete report covering every sample."
        )})
    raise RuntimeError(f"Agent did not finish within {max_turns} turns")


# ----------------------------------------------------------------------------- human prompt
def _ask_human(sid, reason):
    """Ask y/N. Returns (approved, note). N is a normal answer: the review carries on."""
    print(f"\nSample {sid}: resequencing suggested.\nReason: {reason}")
    while True:
        try:
            answer = input("Resequence? [y/N]: ").strip().lower()
        except EOFError:   # no keyboard attached (for example a batch job): never approve silently
            print("\nNo input available, treating this as N.")
            return False, "no human input available"
        if answer in ("y", "yes"):
            return True, ""
        if answer in ("", "n", "no"):
            break
        print("Please type y or n.")
    print(f"Not resequencing {sid}. Carrying on with the remaining samples.")
    try:
        note = input("Optional note for the report (for example 'remap only'), or Enter to skip: ").strip()
    except EOFError:
        note = ""
    return False, note


# ----------------------------------------------------------------------------- sections added by code
def _fmt(v):
    return f"{v:g}" if _is_real_number(v) else ""


def _describe(p):
    if p["status"] == "missing":
        return f"{p['parameter']} missing"
    limit = f"{p['limit_type']} {_fmt(p['limit'])}"
    return f"{p['parameter']} {_fmt(p['value'])} ({limit})"


def flags_section(toolbox):
    """Authoritative threshold flags for every sample, computed from the data, not from the model."""
    lines = ["\n\n## Threshold flags (computed by code)\n",
             "These flags come directly from the QC table and the thresholds file. If the model's table above "
             "disagrees with them, this table is correct.\n",
             "| Sample | Status | Outside the acceptable range | Within the margin of a limit |", "|---|---|---|---|"]
    for sid in sorted(toolbox.qc):
        c = toolbox.check(sid)
        bad = "; ".join(_describe(p) for p in c["parameters"] if p["status"] in ("out_of_range", "missing"))
        near = "; ".join(_describe(p) for p in c["parameters"] if p["status"] == "near_limit")
        lines.append(f"| {sid} | {c['overall']} | {bad or '-'} | {near or '-'} |")
    return "\n".join(lines) + "\n"


def thresholds_section(thresholds, margin, not_assessed=()):
    lines = ["\n\n## Thresholds used\n", "| Parameter | Min | Max | Unit | Note |", "|---|---|---|---|---|"]
    for name, t in thresholds.items():
        lines.append(f"| {name} | {_fmt(t['min']) or '-'} | {_fmt(t['max']) or '-'} | {t['unit']} | {t['note']} |")
    lines.append(f"\nBORDERLINE means inside the range but within {margin:.0%} of a limit.")
    if not_assessed:
        lines.append("\nNo threshold was set for these columns, so they were not assessed: "
                     + ", ".join(not_assessed) + ".")
    return "\n".join(lines) + "\n"


def disagreement_note(toolbox, report):
    """Warn if the model's text calls a code-flagged sample PASS. A safety net, not a proof."""
    suspects = []
    for sid in sorted(toolbox.qc):
        if toolbox.check(sid)["overall"] != "FAIL":
            continue
        for line in report.splitlines():
            if _mentions(line, sid) and re.search(r"\bPASS\b", line) and not re.search(r"\b(FAIL|BORDERLINE)\b", line):
                suspects.append(sid)
                break
    if not suspects:
        return ""
    return ("\n\n**NOTE: the model's table may call these samples PASS although the threshold check flagged them: "
            + ", ".join(suspects) + ". Trust the threshold flags below and check the model's wording.**\n")


def decisions_section(rerun_log):
    """Human decisions as a table, added to the report by code so it never depends on the model."""
    if not rerun_log:
        return "\n\n## Human resequencing decisions\n\nNo resequencing was requested.\n"
    lines = ["\n\n## Human resequencing decisions\n", "| Sample | Decision | Human note |", "|---|---|---|"]
    for r in rerun_log:
        lines.append(f"| {r['sample_id']} | {'resequence approved' if r['approved'] else 'not resequenced'} "
                     f"| {r.get('human_note') or ''} |")
    return "\n".join(lines) + "\n"


def main():
    import anthropic  # imported here so tests can run without the package

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--qc", required=True, help="tab-separated QC table")
    parser.add_argument("--thresholds", required=True,
                        help="tab-separated file of acceptable ranges (see thresholds_example.tsv)")
    parser.add_argument("--borderline-margin", type=float, default=DEFAULT_MARGIN,
                        help="inside the range but within this fraction of a limit is BORDERLINE (0 turns it off)")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--auto-approve", action="store_true",
                        help="approve every resequencing request without asking (demo only)")
    parser.add_argument("--outdir", default="qc_output")
    args = parser.parse_args()
    if not 0 <= args.borderline_margin < 1:
        parser.error("--borderline-margin must be from 0 up to (not including) 1, for example 0.10")

    qc = load_qc(args.qc)
    try:
        thresholds = load_thresholds(args.thresholds)
        not_assessed = validate_thresholds(thresholds, qc)
    except ValueError as exc:
        sys.exit(f"Thresholds problem in {args.thresholds}: {exc}")
    if not_assessed:
        print("No threshold set for (will not be assessed): " + ", ".join(not_assessed))

    approve = (lambda sid, reason: True) if args.auto_approve else _ask_human
    toolbox = Toolbox(qc, thresholds, approve_fn=approve, margin=args.borderline_margin)
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)

    report = None
    try:
        report = run_agent(anthropic.Anthropic(), toolbox, model=args.model)
    finally:   # the human's decisions are saved even if the run fails or is interrupted
        (out / "rerun_log.json").write_text(json.dumps(toolbox.rerun_log, indent=2))

    report += (disagreement_note(toolbox, report) + flags_section(toolbox)
               + thresholds_section(thresholds, args.borderline_margin, not_assessed)
               + decisions_section(toolbox.rerun_log))
    (out / "qc_report.md").write_text(report)
    approved = sum(r["approved"] for r in toolbox.rerun_log)
    print(report)
    by_status = {}
    for sid in sorted(qc):
        by_status.setdefault(toolbox.check(sid)["overall"], []).append(sid)
    for status in ("FAIL", "BORDERLINE"):
        if by_status.get(status):
            print(f"\n{status}: {', '.join(by_status[status])}")
    print(f"\nResequencing requests: {len(toolbox.rerun_log)} "
          f"({approved} approved, {len(toolbox.rerun_log) - approved} declined)")
    print(f"Saved to {out}/ (report and rerun log)")


if __name__ == "__main__":
    main()
