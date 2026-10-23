# WGS QC report (12 samples)

Thresholds: mean coverage ≥ 15, % mapped ≥ 85, % genome ≥10x ≥ 80, freemix ≤ 0.03. I called a sample BORDERLINE if it passes but is within 10% of a threshold.

| Sample | Status | Reason | Action |
|---|---|---|---|
| DEMO001 | PASS | cov 32.4, mapped 97.1, 10x 95.2, freemix 0.004 | None |
| DEMO002 | PASS | cov 28.9, mapped 96.5, 10x 93.8, freemix 0.006 | None |
| DEMO003 | **FAIL** | cov 6.2, 10x 22.5 (mapped 91.3 and freemix 0.005 are OK) | **Rerun requested** (RUN02, under-sequenced) |
| DEMO004 | BORDERLINE | cov 16.1 (threshold 15), 10x 82.4 (threshold 80); mapped and freemix OK | Use with caution. No rerun. |
| DEMO005 | **FAIL** | mapped 72.4 (min 85); cov 30.2, 10x 90.1 and freemix 0.005 are OK | **Rerun/re-alignment requested** (RUN03) |
| DEMO006 | **FAIL** | freemix 0.081 (max 0.03), about 2.7× the limit; other metrics fine | **Exclude or re-extract.** No rerun, because contamination is not fixed by re-sequencing. |
| DEMO007 | PASS | cov 35.0, mapped 97.4, 10x 96.0, freemix 0.003 | None |
| DEMO008 | BORDERLINE | mapped 88.9 (threshold 85), 10x 86.5 (threshold 80); cov 24.3 and freemix 0.009 OK | Use with caution. No rerun. |
| DEMO009 | **FAIL** | cov 11.8, 10x 61.3 (mapped 94.2 and freemix 0.006 are OK) | **Rerun requested** (RUN02, under-sequenced) |
| DEMO010 | **FAIL** | freemix 0.032 (max 0.03); other metrics fine | **Exclude or re-extract**, or have a human review it. No rerun. |
| DEMO011 | PASS | cov 31.1, mapped 97.0, 10x 94.9, freemix 0.004 | None |
| DEMO012 | BORDERLINE | freemix 0.027, which is exactly 10% below the 0.03 limit; other metrics fine | Use with caution. Consider a contamination re-check. |

**Please double-check:**
- **DEMO010:** Its freemix of 0.032 is only just over the limit, so a strict cutoff fails it. The call is close enough that a human may want to decide whether to exclude it or re-extract it.
- **DEMO012:** Its freemix of 0.027 sits exactly on my 10% borderline boundary. I classed it as BORDERLINE, and it is a judgement call.
- **DEMO004 and DEMO008:** Both are borderline. DEMO004 is close to the minimum on coverage and 10x breadth. DEMO008 is close on mapping and 10x breadth.
- **Run-level patterns:** Both coverage failures (DEMO003 and DEMO009) came from RUN02, which suggests a run or library-prep problem there. RUN03 has the low-mapping sample (DEMO005), the contaminated sample (DEMO006) and the borderline DEMO008. That points to a possible RUN03 issue such as the reference, adapters or sample handling.
- **DEMO005 rerun:** Check the reference and trimming before re-sequencing. A low mapping rate can also come from non-target DNA, which a rerun won't fix.
- **Rerun requests:** I requested reruns for DEMO003, DEMO005 and DEMO009. The tool only reported them as queued in a demo stub, so nothing has actually run, and a human still needs to approve them.