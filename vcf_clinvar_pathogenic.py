#!/usr/bin/env python3
"""
vcf_clinvar_pathogenic.py

Query ClinVar for VCF variants (GRCh37 or GRCh38) using SPDI
and output variants classified as Pathogenic or Likely pathogenic,
optionally requiring a minimum ClinVar review-star threshold.
"""

import argparse
import csv
import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple
import requests


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
    "4": "NC_000004.11", "5": "NC_000005.9", "6": "NC_000006.11",
    "7": "NC_000007.13", "8": "NC_000008.10", "9": "NC_000009.11",
    "10": "NC_000010.10", "11": "NC_000011.9", "12": "NC_000012.11",
    "13": "NC_000013.10", "14": "NC_000014.8", "15": "NC_000015.9",
    "16": "NC_000016.9", "17": "NC_000017.10", "18": "NC_000018.9",
    "19": "NC_000019.9", "20": "NC_000020.10", "21": "NC_000021.8",
    "22": "NC_000022.10", "X": "NC_000023.10", "Y": "NC_000024.9",
    "MT": "NC_012920.1", "M": "NC_012920.1",
}

GRCH36_REFSEQ = {
    "1": "NC_000001.9", "2": "NC_000002.10", "3": "NC_000003.10",
    "4": "NC_000004.10", "5": "NC_000005.8", "6": "NC_000006.10",
    "7": "NC_000007.12", "8": "NC_000008.9", "9": "NC_000009.10",
    "10": "NC_000010.9", "11": "NC_000011.8", "12": "NC_000012.10",
    "13": "NC_000013.9", "14": "NC_000014.7", "15": "NC_000015.8",
    "16": "NC_000016.8", "17": "NC_000017.9", "18": "NC_000018.8",
    "19": "NC_000019.8", "20": "NC_000020.9", "21": "NC_000021.7",
    "22": "NC_000022.9", "X": "NC_000023.9", "Y": "NC_000024.8",
    "MT": "NC_001807.4", "M": "NC_001807.4",
}

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def normalize_chrom(chrom: str) -> str:
    c = chrom.strip()
    if c.lower().startswith("chr"):
        c = c[3:]
    return c.upper()


def get_refseq_accession(chrom: str, assembly: str) -> Optional[str]:
    chrom = normalize_chrom(chrom)
    if assembly == "GRCh38":
        return GRCH38_REFSEQ.get(chrom)
    if assembly == "GRCh37":
        return GRCH37_REFSEQ.get(chrom)
    if assembly == "GRCh36":
        return GRCH36_REFSEQ.get(chrom)
    return None


def vcf_to_spdi(chrom: str, pos: int, ref: str, alt: str, assembly: str) -> Optional[str]:
    acc = get_refseq_accession(chrom, assembly)
    if not acc:
        return None
    spdi_pos = pos - 1
    return f"{acc}:{spdi_pos}:{ref}:{alt}"


def is_pathogenic(label: str) -> bool:
    if not label:
        return False
    x = label.lower()
    return "pathogenic" in x and "benign" not in x


def review_status_to_stars(review_status: str) -> int:
    """
    Map ClinVar aggregate review status text to star count.
    """
    if not review_status:
        return 0

    x = review_status.strip().lower()

    if "practice guideline" in x:
        return 4
    if "reviewed by expert panel" in x:
        return 3
    if "criteria provided, multiple submitters, no conflicts" in x:
        return 2
    if "criteria provided, single submitter" in x:
        return 1

    # Catch common lower-confidence states
    if (
        "conflicting classifications" in x
        or "no assertion criteria provided" in x
        or "no assertion provided" in x
    ):
        return 0

    return 0


def _get_with_retry(url: str, params: Dict[str, str], max_retries: int = 3) -> requests.Response:
    """GET with retry on 429 (rate limit). Uses longer sleep after 429."""
    for attempt in range(max_retries):
        r = requests.get(url, params=params, timeout=30)
        if r.status_code != 429:
            return r
        if attempt < max_retries - 1:
            time.sleep(2.0 * (attempt + 1))
    return r


def _extract_clinical_classification(obj: Dict[str, Any]) -> tuple:
    """
    Extract clinical significance description and review_status from a ClinVar
    esummary result item. Handles current API (germline_classification, etc.)
    and legacy top-level clinical_significance / review_status.
    Returns (description: str, review_status: str).
    """
    # Current API: classification under germline_classification, clinical_impact_classification, oncogenicity_classification
    for key in ("germline_classification", "clinical_impact_classification", "oncogenicity_classification"):
        block = obj.get(key)
        if isinstance(block, dict):
            desc = block.get("description") or ""
            rev = block.get("review_status") or ""
            if desc or rev:
                return (desc.strip(), rev.strip())
    # Legacy API: top-level clinical_significance and review_status
    cs = obj.get("clinical_significance")
    if isinstance(cs, dict):
        label = (cs.get("description") or "").strip()
    else:
        label = (str(cs).strip() if cs is not None else "")
    rev = (obj.get("review_status") or "").strip()
    return (label, rev)


def clinvar_lookup(
    spdi: str, min_stars: int = 0
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """
    Query ClinVar by SPDI. Returns (hit_dict or None, log_entry for diagnostics).
    """
    log_entry: Dict[str, Any] = {
        "spdi": spdi,
        "esearch_url": None,
        "esummary_url": None,
        "esearch_ids": [],
        "esearch_count": 0,
        "records": [],
        "returned_hit": None,
    }

    search_url = f"{EUTILS_BASE}/esearch.fcgi"
    search_params = {"db": "clinvar", "retmode": "json", "term": spdi}
    r = _get_with_retry(search_url, search_params)
    log_entry["esearch_url"] = r.url
    r.raise_for_status()
    data = r.json()
    ids = data.get("esearchresult", {}).get("idlist", [])
    log_entry["esearch_ids"] = ids
    log_entry["esearch_count"] = len(ids)

    if not ids:
        return None, log_entry

    summary_url = f"{EUTILS_BASE}/esummary.fcgi"
    summary_params = {"db": "clinvar", "retmode": "json", "id": ",".join(ids)}
    r = _get_with_retry(summary_url, summary_params)
    log_entry["esummary_url"] = r.url
    r.raise_for_status()
    summary = r.json().get("result", {})

    for cid in ids:
        obj = summary.get(cid)
        if not obj:
            log_entry["records"].append({
                "clinvar_id": cid,
                "error": "missing in esummary result",
                "clinical_significance": None,
                "review_status": None,
                "stars": None,
                "is_pathogenic": False,
                "passed_min_stars": False,
            })
            continue

        label, review_status = _extract_clinical_classification(obj)
        stars = review_status_to_stars(review_status)
        pathogenic = is_pathogenic(label)
        passed_stars = stars >= min_stars

        log_entry["records"].append({
            "clinvar_id": cid,
            "clinical_significance": label,
            "review_status": review_status,
            "stars": stars,
            "is_pathogenic": pathogenic,
            "passed_min_stars": passed_stars,
        })

        if pathogenic and passed_stars:
            hit = {
                "clinvar_id": cid,
                "clinical_significance": label,
                "review_status": review_status,
                "stars": stars,
            }
            log_entry["returned_hit"] = hit
            return hit, log_entry

    return None, log_entry


def _write_log_entry(log_file, log_entry: Dict[str, Any], min_stars: int) -> None:
    """Write a single clinvar_lookup result to the log file for diagnostics."""
    lines = [
        "",
        "---",
        f"SPDI: {log_entry['spdi']}",
        f"esearch URL: {log_entry.get('esearch_url', '')}",
        f"esearch: count={log_entry['esearch_count']}, ids={log_entry['esearch_ids']}",
    ]
    if log_entry.get("esummary_url"):
        lines.append(f"esummary URL: {log_entry['esummary_url']}")
    for i, rec in enumerate(log_entry.get("records", []), 1):
        sig = rec.get("clinical_significance")
        rev = rec.get("review_status")
        stars = rec.get("stars")
        path = rec.get("is_pathogenic")
        passed = rec.get("passed_min_stars")
        err = rec.get("error")
        if err:
            lines.append(f"  record {i} (id={rec.get('clinvar_id')}): {err}")
        else:
            why = "HIT" if (path and passed) else ("pathogenic but stars < " + str(min_stars) if path else "not pathogenic")
            lines.append(
                f"  record {i}: id={rec.get('clinvar_id')} "
                f"significance={repr(sig)} review_status={repr(rev)} stars={stars} "
                f"is_pathogenic={path} passed_min_stars={passed} => {why}"
            )
    lines.append(f"returned_hit: {log_entry.get('returned_hit') is not None}")
    log_file.write("\n".join(lines) + "\n")
    log_file.flush()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vcf", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--assembly", choices=["GRCh36", "GRCh37", "GRCh38"], default="GRCh38")
    parser.add_argument(
        "--min-stars",
        type=int,
        choices=[0, 1, 2, 3, 4],
        default=2,
        help="Minimum ClinVar aggregate review stars required (default: 2)"
    )
    parser.add_argument(
        "--log",
        metavar="FILE",
        default=None,
        help="Write a diagnostic log of ClinVar lookup results to FILE (for debugging parsing)"
    )
    args = parser.parse_args()

    total = 0
    hits = 0
    log_file = open(args.log, "w", encoding="utf-8") if args.log else None

    try:
        with open(args.vcf) as vcf, open(args.out, "w", newline="") as out:
            writer = csv.writer(out, delimiter="\t")
            writer.writerow([
                "CHROM", "POS", "REF", "ALT",
                "ClinVarID", "Significance", "ReviewStatus", "Stars"
            ])

            for line in vcf:
                if line.startswith("#"):
                    continue

                raw = line.rstrip("\n")
                fields = raw.split("\t")
                if len(fields) < 5:
                    fields = re.split(r"\s+", raw.strip())
                if len(fields) < 5:
                    continue

                total += 1
                chrom, pos, vid, ref, alt = fields[:5]
                pos = int(pos)

                for a in alt.split(","):
                    spdi = vcf_to_spdi(chrom, pos, ref, a, args.assembly)
                    if not spdi:
                        continue

                    result, log_entry = clinvar_lookup(spdi, min_stars=args.min_stars)
                    time.sleep(0.34)

                    if log_file is not None:
                        _write_log_entry(log_file, log_entry, args.min_stars)

                    if result:
                        hits += 1
                        writer.writerow([
                            chrom, pos, ref, a,
                            result["clinvar_id"],
                            result["clinical_significance"],
                            result["review_status"],
                            result["stars"],
                        ])

        print(f"Processed {total} variants, found {hits} hits with min-stars >= {args.min_stars}.")
    finally:
        if log_file is not None:
            log_file.close()


if __name__ == "__main__":
    main()