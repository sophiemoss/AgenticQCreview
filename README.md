# Agentic QC review of genome sequencing data
## Screening sequencing QC data and suggesting reruns where required
### Human-in-the-loop design

```bash
python qc_agent.py --qc data/qc_demo.tsv
```

`data/qc_demo.tsv` is **simulated** (made by `make_demo_qc.py`), so it is safe to share. 

The thresholds in `qc_agent.py` are illustrative: please set them for your own sequencing requirements.