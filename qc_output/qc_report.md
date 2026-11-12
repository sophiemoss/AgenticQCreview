# WGS QC review: 12 Anopheles samples

Thresholds: mean coverage ≥15x, mapped ≥85%, genome covered ≥75%, genome ≥10x ≥60%, freemix ≤0.03. The borderline margin is 10%. All statuses below are as returned by `check_sample`.

| Sample | Status | Out of range / near limit | Reasoning | Action |
|---|---|---|---|---|
| DEMO001 | PASS | None | All metrics are within range. | Accept |
| DEMO002 | PASS | None | All metrics are within range. | Accept |
| DEMO003 | FAIL | Out of range: mean_coverage 6.2x (min 15); pct_genome_covered 48.0% (min 75); pct_genome_10x 41.0% (min 60). Near limit: pct_mapped 93.5% (min 85). | Depth and coverage are all low, while mapping and contamination are fine (freemix 0.003). This looks like an under-sequenced library. I can't tell from these numbers whether the library complexity is adequate. | **Resequence.** I requested it, and the request is queued. The tool output didn't show a human approval or decline, only "queued". |
| DEMO004 | PASS | None | All metrics are within range. | Accept |
| DEMO005 | PASS | None | All metrics are within range. | Accept |
| DEMO006 | FAIL | Out of range: freemix 0.12 (max 0.03). | Depth, mapping and coverage are good, and only contamination fails. Resequencing won't remove contamination. The numbers can't show whether it comes from cross-sample or other-DNA contamination. | **Re-extract**, or exclude if no re-extraction is possible. I did not request resequencing. |
| DEMO007 | FAIL | Out of range: pct_genome_covered 55.0% (min 75); pct_genome_10x 40.0% (min 60). | Mean depth is adequate (18.0x) but the fraction of the genome covered is low. This suggests uneven coverage. Possible causes include library bias, repeat or reference issues, or a few regions with very high depth. I can't tell which from the numbers. Simply adding more reads is unlikely to fix this. | **Reprocess/inspect existing data:** check the coverage distribution, duplicates and the reference. Consider a new library prep if the unevenness is real. I did not request resequencing. |
| DEMO008 | PASS | None | All metrics are within range. | Accept |
| DEMO009 | FAIL | Out of range: pct_mapped 61.5% (min 85). | Depth and genome coverage are good (28.0x, 92.0%) and freemix is low (0.004). Low mapping with adequate depth may point to non-target DNA or a reference mismatch. The numbers can't confirm either cause. | **Check the species call and reference, then remap.** I did not request resequencing. |
| DEMO010 | PASS | None | All metrics are within range. | Accept |
| DEMO011 | BORDERLINE | Near limit: mean_coverage 16.0x (min 15); pct_mapped 93.5% (min 85). | Nothing is out of range, but depth is close to the minimum. Coverage and contamination are fine. | **Accept with a note** that depth is marginal. Resequencing is not needed. |
| DEMO012 | FAIL | Out of range: freemix 0.8 (max 0.03). Missing: pct_mapped (no value). | Contamination is very high. The missing mapping value means this metric couldn't be judged. The other metrics look fine, but they are unreliable given the contamination. | **Exclude**, or re-extract if the material is available. Investigate why pct_mapped is missing. I did not request resequencing. |

**For a human to double-check:**
- **DEMO003:** confirm the resequencing decision. The tool only reported "queued (demo stub, nothing executed)", so nothing has actually run.
- **DEMO007:** I chose not to request resequencing because the pattern suggests uneven coverage. A human may disagree and want more data.
- **DEMO009:** confirm the species and reference.
- **DEMO012:** the missing pct_mapped may be a pipeline or data-entry fault. Freemix of 0.8 is extreme and could be a sample swap or a metric error as well as real contamination.
- **DEMO006 and DEMO012:** the contamination source is unknown.
- **DEMO011:** keep an eye on the marginal depth if it will be used for analyses that need higher coverage.

## Threshold flags (computed by code)

These flags come directly from the QC table and the thresholds file. If the model's table above disagrees with them, this table is correct.

| Sample | Status | Outside the acceptable range | Within the margin of a limit |
|---|---|---|---|
| DEMO001 | PASS | - | - |
| DEMO002 | PASS | - | - |
| DEMO003 | FAIL | mean_coverage 6.2 (min 15); pct_genome_covered 48 (min 75); pct_genome_10x 41 (min 60) | pct_mapped 93.5 (min 85) |
| DEMO004 | PASS | - | - |
| DEMO005 | PASS | - | - |
| DEMO006 | FAIL | freemix 0.12 (max 0.03) | - |
| DEMO007 | FAIL | pct_genome_covered 55 (min 75); pct_genome_10x 40 (min 60) | - |
| DEMO008 | PASS | - | - |
| DEMO009 | FAIL | pct_mapped 61.5 (min 85) | - |
| DEMO010 | PASS | - | - |
| DEMO011 | BORDERLINE | - | mean_coverage 16 (min 15); pct_mapped 93.5 (min 85) |
| DEMO012 | FAIL | pct_mapped missing; freemix 0.8 (max 0.03) | - |


## Thresholds used

| Parameter | Min | Max | Unit | Note |
|---|---|---|---|---|
| mean_coverage | 15 | - | x | Mean sequencing depth across the genome |
| pct_mapped | 85 | - | % | Percentage of reads mapped to the reference |
| pct_genome_covered | 75 | - | % | Percentage of the genome covered (60% or more is acceptable) |
| pct_genome_10x | 60 | - | % | Percentage of the genome covered at 10x or more |
| freemix | - | 0.03 | fraction | Contamination estimate (FREEMIX); lower is better |

BORDERLINE means inside the range but within 10% of a limit.

No threshold was set for these columns, so they were not assessed: species.


## Human resequencing decisions

| Sample | Decision | Human note |
|---|---|---|
| DEMO003 | resequence approved |  |
