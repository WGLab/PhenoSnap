# Monthly ClinVar pathogenic scan heartbeat

Purpose:
Check once per calendar month whether ./monthly.vcf contains any ClinVar Pathogenic or Likely pathogenic variants
using ./PhenoSnap/vcf_clinvar_pathogenic.py. Only alert if there is at least one hit.

Strict rules:
- Run this exact command with the exec tool from the workspace:
  python3 ./scripts/monthly_clinvar_heartbeat.py
- Do not improvise a different workflow.
- If the script prints exactly `HEARTBEAT_OK`, reply exactly `HEARTBEAT_OK`.
- Otherwise, return the script output exactly, with no added commentary.
- Do not send a message for clean runs.
- If required files are missing or the script fails, send the script output as the alert.

Files:
- Input VCF: ./monthly.vcf
- ClinVar script: ./PhenoSnap/vcf_clinvar_pathogenic.py
- Output TSV: ./monthly_clinvar_pathogenic.tsv
- State file: ./state/monthly_clinvar_state.json
- Heartbeat runner: ./scripts/monthly_clinvar_heartbeat.py