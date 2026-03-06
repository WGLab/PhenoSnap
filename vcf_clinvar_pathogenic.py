#!/usr/bin/env python3
"""
vcf_clinvar_pathogenic.py

Query ClinVar for VCF variants (GRCh37 or GRCh38) using SPDI
and output variants classified as Pathogenic or Likely pathogenic.

Usage:
  python vcf_clinvar_pathogenic.py \
      --vcf input.vcf \
      --out hits.tsv \
      --assembly GRCh38
"""

import argparse
import csv
import sys
import time
from typing import Dict, Optional, List
import requests


# ---------------------------
# Chromosome → RefSeq mapping
# ---------------------------

GRCH38_REFSEQ = {
    "1": "NC_000001.11", "2": "NC_000002.12", "3": "NC_000003.12",
    "4": "NC_000004.12", "5": "NC_000005.10", "6": "NC_000006.12",
    "7": "NC_000007.14", "8": "NC_000008.11", "9": "NC_000009.12",
    "10": "NC_000010.11", "11": "NC_000011.10", "12": "NC_000012.12",
    "13": "NC_000013.11", "14": "NC_000014.9", "15": "NC_000015.10",
    "16": "NC_000016.10", "17": "NC_000017.11", "18": "NC_000018.10",
    "19": "NC_000019.10", "20": "NC_000020.11", "21": "NC_000021.9",
    "22": "NC_000022.11", "X": "NC_000023.11", "Y": "NC_000024.10",
    "MT": "NC_012920.1", "M": "NC_012920.1",
}

GRCH37_REFSEQ = {
    "1": "NC_000001.10", "2": "NC_000002.11", "3": "NC_000003.11",
    "4": "NC_000004.11", "5": "NC_000005.9",  "6": "NC_000006.11",
    "7": "NC_000007.13", "8": "NC_000008.10", "9": "NC_000009.11",
    "10": "NC_000010.10", "11": "NC_000011.9", "12": "NC_000012.11",
    "13": "NC_000013.10", "14": "NC_000014.8", "15": "NC_000015.9",
    "16": "NC_000016.9", "17": "NC_000017.10", "18": "NC_000018.9",
    "19": "NC_000019.9", "20": "NC_000020.10", "21": "NC_000021.8",
    "22": "NC_000022.10", "X": "NC_000023.10", "Y": "NC_000024.9",
    "MT": "NC_012920.1", "M": "NC_012920.1",
}

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


# ---------------------------
# Utility Functions
# ---------------------------

def normalize_chrom(chrom: str) -> str:
    c = chrom.strip()
    if c.lower().startswith("chr"):
        c = c[3:]
    return c.upper()


def get_refseq_accession(chrom: str, assembly: str) -> Optional[str]:
    chrom = normalize_chrom(chrom)
    if assembly == "GRCh38":
        return GRCH38_REFSEQ.get(chrom)
    elif assembly == "GRCh37":
        return GRCH37_REFSEQ.get(chrom)
    return None


def vcf_to_spdi(chrom: str, pos: int, ref: str, alt: str, assembly: str) -> Optional[str]:
    acc = get_refseq_accession(chrom, assembly)
    if not acc:
        return None
    spdi_pos = pos - 1  # SPDI uses 0-based coordinate
    return f"{acc}:{spdi_pos}:{ref}:{alt}"


def is_pathogenic(label: str) -> bool:
    if not label:
        return False
    label = label.lower()
    return "pathogenic" in label and "benign" not in label


def clinvar_lookup(spdi: str) -> Optional[dict]:
    # esearch
    search_url = f"{EUTILS_BASE}/esearch.fcgi"
    r = requests.get(search_url, params={
        "db": "clinvar",
        "retmode": "json",
        "term": spdi
    })
    data = r.json()
    ids = data.get("esearchresult", {}).get("idlist", [])
    if not ids:
        return None

    # esummary
    summary_url = f"{EUTILS_BASE}/esummary.fcgi"
    r = requests.get(summary_url, params={
        "db": "clinvar",
        "retmode": "json",
        "id": ",".join(ids)
    })
    summary = r.json().get("result", {})

    for cid in ids:
        obj = summary.get(cid)
        if not obj:
            continue
        cs = obj.get("clinical_significance", {})
        label = cs.get("description")
        if is_pathogenic(label):
            return {
                "clinvar_id": cid,
                "clinical_significance": label,
                "review_status": obj.get("review_status", "")
            }

    return None


# ---------------------------
# Main
# ---------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vcf", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--assembly", choices=["GRCh37", "GRCh38"], default="GRCh38")
    args = parser.parse_args()

    total = 0
    hits = 0

    with open(args.vcf) as vcf, open(args.out, "w", newline="") as out:
        writer = csv.writer(out, delimiter="\t")
        writer.writerow(["CHROM", "POS", "REF", "ALT", "ClinVarID", "Significance", "ReviewStatus"])

        for line in vcf:
            if line.startswith("#"):
                continue
            total += 1
            fields = line.strip().split("\t")
            chrom, pos, vid, ref, alt = fields[:5]
            pos = int(pos)

            for a in alt.split(","):
                spdi = vcf_to_spdi(chrom, pos, ref, a, args.assembly)
                if not spdi:
                    continue

                result = clinvar_lookup(spdi)
                time.sleep(0.34)  # rate limiting (~3 req/sec)

                if result:
                    hits += 1
                    writer.writerow([
                        chrom, pos, ref, a,
                        result["clinvar_id"],
                        result["clinical_significance"],
                        result["review_status"]
                    ])

    print(f"Processed {total} variants, found {hits} pathogenic/likely pathogenic hits.")


if __name__ == "__main__":
    main()