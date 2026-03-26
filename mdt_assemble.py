#!/usr/bin/env python3
"""
mdt_assemble.py

Reads all clinical data files from a patient folder and consolidates
them into a single digital twin state JSON file.

Usage:
    python3 rdmdt_assemble.py --input-dir ./patient_data --out twin_state.json

Supported input files (matched by extension):
    *.vcf   -> genotype data (variants)
    *.json  -> PhenoPacket (HPO terms, medications, family history)
"""

import argparse
import glob
import json
import os
from datetime import datetime, timezone


def read_vcf(path):
    """Read a VCF file and return variant list and assembly info."""
    variants = []
    assembly = None
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("##reference="):
                assembly = line.split("=", 1)[1]
                continue
            if line.startswith("#"):
                continue
            fields = line.split("\t")
            if len(fields) < 5:
                fields = line.split()
            if len(fields) < 5:
                continue
            for alt in fields[4].split(","):
                variants.append({
                    "chrom": fields[0],
                    "pos": int(fields[1]),
                    "ref": fields[3],
                    "alt": alt,
                    "genotype": fields[9] if len(fields) >= 10 else None,
                })
    return {"reference_assembly": assembly, "variants": variants}


def read_phenopacket(path):
    """Read a PhenoPacket JSON and return structured content."""
    with open(path) as f:
        data = json.load(f)

    features = []
    for feat in data.get("phenotypicFeatures", []):
        t = feat.get("type", {})
        entry = {
            "hpo_id": t.get("id"),
            "hpo_label": t.get("label"),
            "excluded": feat.get("excluded", False),
        }
        onset = feat.get("onset", {}).get("age", {}).get("iso8601duration")
        if onset:
            entry["onset"] = onset
        features.append(entry)

    medications = []
    for action in data.get("medicalActions", []):
        agent = action.get("treatment", {}).get("agent", {})
        if agent.get("label"):
            medications.append(agent["label"])

    return {
        "created": data.get("metaData", {}).get("created"),
        "phenotypic_features": features,
        "medications": medications,
        "notes": data.get("metaData", {}).get("notes", []),
        "subject": data.get("subject", {}),
    }


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_dir = os.path.join(script_dir, "patient_latest_status")
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", default=default_dir)
    parser.add_argument("--out", default=os.path.join(default_dir, "twin_state.json"))
    args = parser.parse_args()

    twin = {
        "assembled_at": datetime.now(timezone.utc).isoformat(),
        "genotype": None,
        "phenotype": None,
    }

    for path in sorted(glob.glob(os.path.join(args.input_dir, "*.vcf"))):
        print(f"Reading VCF: {path}")
        twin["genotype"] = read_vcf(path)

    for path in sorted(glob.glob(os.path.join(args.input_dir, "*.json"))):
        print(f"Reading PhenoPacket: {path}")
        twin["phenotype"] = read_phenopacket(path)

    with open(args.out, "w") as f:
        json.dump(twin, f, indent=2, ensure_ascii=False)
    print(f"Output: {args.out}")


if __name__ == "__main__":
    main()