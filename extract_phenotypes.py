import argparse
import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import obonet
import spacy
from spacy.matcher import PhraseMatcher


def parse_hpo_obo(
    obo_path: Path,
    min_words: int = 1,
    max_words: int = 8,
) -> Tuple[Dict[str, Set[str]], Dict[str, str]]:
    """
    Parse an HPO .obo file and build:

    - phrase_to_ids: normalized phrase -> set of HPO IDs
    - id_to_label: HPO ID -> primary label
    """
    graph = obonet.read_obo(str(obo_path))

    phrase_to_ids: Dict[str, Set[str]] = {}
    id_to_label: Dict[str, str] = {}

    def add_phrase(phrase: str, hpo_id: str):
        norm = normalize_phrase(phrase)
        if not norm:
            return
        word_count = len(norm.split())
        if word_count < min_words or word_count > max_words:
            return
        phrase_to_ids.setdefault(norm, set()).add(hpo_id)

    for hpo_id, data in graph.nodes(data=True):
        name = data.get("name")
        if not name:
            continue
        id_to_label[hpo_id] = name
        add_phrase(name, hpo_id)

        # HPO synonyms are stored like: "\"short stature\" EXACT []"
        for syn in data.get("synonym", []):
            m = re.match(r'"(.+?)"', syn)
            if m:
                add_phrase(m.group(1), hpo_id)

    return phrase_to_ids, id_to_label


def load_spacy_model(model_name: str = "en_core_web_sm"):
    """
    Load a local spaCy model. Raises a clear error if the model is missing.
    """
    try:
        return spacy.load(model_name)
    except OSError as exc:
        raise SystemExit(
            f"spaCy model '{model_name}' is not installed.\n"
            f"Install it with:\n\n"
            f"  python -m spacy download {model_name}\n"
        ) from exc


def normalize_phrase(text: str) -> str:
    """
    Normalize a phrase for dictionary matching.
    Lowercase, collapse whitespace, and strip punctuation at edges.
    """
    # Lowercase and strip
    text = text.lower().strip()
    # Replace non-word characters (except spaces and hyphens) with space
    text = re.sub(r"[^\w\s\-]", " ", text)
    # Collapse multiple whitespace
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def build_phrase_matcher(nlp, phrase_to_ids: Dict[str, Set[str]]) -> PhraseMatcher:
    """
    Build a spaCy PhraseMatcher using all HPO phrases.
    
    Returns a PhraseMatcher configured to match HPO phrases case-insensitively.
    """
    matcher = PhraseMatcher(nlp.vocab, attr="LOWER")
    patterns = []
    
    for phrase in phrase_to_ids.keys():
        # Create a doc from the phrase for matching
        doc = nlp.make_doc(phrase)
        patterns.append(doc)
    
    if patterns:
        matcher.add("HPO_TERMS", patterns)
    
    return matcher


def is_negated_spacy(doc, token_start: int, token_end: int) -> bool:
    """
    Check if a span of tokens is negated using spaCy's dependency parsing.
    
    Uses spaCy's dependency tree to detect negation tokens (dep_ == 'neg')
    and checks if they affect the given span by analyzing the dependency subtree.
    """
    # Get the span
    span = doc[token_start:token_end]
    
    # Find all negation tokens in the same sentence
    sent = span.sent
    negation_tokens = [tok for tok in sent if tok.dep_ == 'neg']
    
    if not negation_tokens:
        # Also check for common negation patterns in the sentence
        sent_text = sent.text.lower()
        span_text_lower = span.text.lower()
        
        # Common negation patterns
        negation_patterns = [
            r'\bno\s+history\s+of\b',
            r'\bno\s+evidence\s+of\b',
            r'\bno\s+signs?\s+of\b',
            r'\babsence\s+of\b',
            r'\bdenies\b',
            r'\bdenied\b',
            r'\bnegative\s+for\b',
            r'\bwithout\b',
            r'\bnot\s+present\b',
            r'\bnot\s+found\b',
        ]
        
        # Check if span text appears after a negation pattern in the sentence
        for pattern in negation_patterns:
            matches = list(re.finditer(pattern, sent_text))
            for match in matches:
                # Check if the span appears after this negation pattern
                span_pos = sent_text.find(span_text_lower, match.end())
                if span_pos != -1:
                    # Verify they're reasonably close (within 50 chars)
                    if span_pos - match.end() < 50:
                        return True
        return False
    
    # Check if any negation token affects this span
    for neg_token in negation_tokens:
        # Get the head of the negation (what is being negated)
        neg_head = neg_token.head
        
        # Get all tokens in the negation head's subtree (what is negated)
        negated_subtree = set()
        negated_subtree.add(neg_head.i)
        
        # Collect all descendants of the negation head
        for token in sent:
            if token.i == neg_head.i:
                continue
            # Check if token is a descendant of neg_head
            current = token
            while current.head != current:  # Not root
                if current.head.i == neg_head.i:
                    negated_subtree.add(token.i)
                    break
                current = current.head
        
        # Check if any token in our span is in the negated subtree
        for i in range(token_start, token_end):
            if i in negated_subtree:
                return True
        
        # Also check if negation head is close to our span and in same sentence
        # This handles cases like "no history of seizures" where "history" is the head
        if abs(neg_head.i - token_start) <= 5:
            return True
    
    return False


def extract_age_of_onset(text: str) -> Optional[Dict[str, str]]:
    """
    Extract age of onset information from text.
    
    Returns a dict with 'iso8601duration' (ISO 8601 format) or None if not found.
    Examples: "14-month-old" -> "P14M", "at age 2 years" -> "P2Y"
    """
    # Pattern for age expressions like "14-month-old", "2-year-old", "3 years old"
    age_patterns = [
        (r'(\d+)[-\s]month[-\s]old', lambda m: f"P{int(m.group(1))}M"),
        (r'(\d+)[-\s]year[-\s]old', lambda m: f"P{int(m.group(1))}Y"),
        (r'(\d+)[-\s]day[-\s]old', lambda m: f"P{int(m.group(1))}D"),
        (r'(\d+)[-\s]week[-\s]old', lambda m: f"P{int(m.group(1))}W"),
        (r'at age (\d+)[-\s]month', lambda m: f"P{int(m.group(1))}M"),
        (r'at age (\d+)[-\s]year', lambda m: f"P{int(m.group(1))}Y"),
        (r'age (\d+)[-\s]month', lambda m: f"P{int(m.group(1))}M"),
        (r'age (\d+)[-\s]year', lambda m: f"P{int(m.group(1))}Y"),
        (r'(\d+)[-\s]years?[-\s]of[-\s]age', lambda m: f"P{int(m.group(1))}Y"),
        (r'(\d+)[-\s]months?[-\s]of[-\s]age', lambda m: f"P{int(m.group(1))}M"),
    ]
    
    for pattern, converter in age_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                return {"iso8601duration": converter(match)}
            except (IndexError, ValueError) as e:
                # Skip if group access fails or conversion fails
                continue
    
    return None


def extract_family_history(text: str) -> List[Dict[str, str]]:
    """
    Extract family history mentions from text.
    
    Returns a list of dicts with 'relation' and 'condition' keys.
    Only extracts mentions that explicitly refer to family members, not the patient.
    """
    family_history = []
    
    # Patient pronouns and terms to exclude
    patient_terms = {'he', 'she', 'patient', 'pt', 'subject', 'proband', 'him', 'her', 'his', 'hers'}
    
    # Patterns for family history mentions - only explicit family relationships
    # Each tuple: (pattern, relation, group_index_for_condition, extract_relation_from_group)
    # If extract_relation_from_group is True, relation comes from group 1, condition from group_idx
    patterns = [
        (r'family history of ([^.]+)', 'family', 1, False),
        (r'family history[^:]*:\s*([^.]+)', 'family', 1, False),
        (r'father has ([^.]+)', 'father', 1, False),
        (r'mother has ([^.]+)', 'mother', 1, False),
        (r'parent has ([^.]+)', 'parent', 1, False),
        (r'sibling has ([^.]+)', 'sibling', 1, False),
        (r'brother has ([^.]+)', 'brother', 1, False),
        (r'sister has ([^.]+)', 'sister', 1, False),
        (r'son has ([^.]+)', 'son', 1, False),
        (r'daughter has ([^.]+)', 'daughter', 1, False),
        (r'father\'s ([^.]+)', 'father', 1, False),
        (r'mother\'s ([^.]+)', 'mother', 1, False),
        (r'parent\'s ([^.]+)', 'parent', 1, False),
        (r'maternal ([^.]+)', 'maternal', 1, False),
        (r'paternal ([^.]+)', 'paternal', 1, False),
        (r'maternal family history of ([^.]+)', 'maternal', 1, False),
        (r'paternal family history of ([^.]+)', 'paternal', 1, False),
        # Pattern that extracts relation dynamically from the match
        (r'\b(father|mother|parent|sibling|brother|sister|son|daughter|grandfather|grandmother|uncle|aunt|cousin)\s+has\s+([^.]+)', None, 2, True),
    ]
    
    for pattern, relation, group_idx, extract_relation_from_group in patterns:
        matches = re.finditer(pattern, text, re.IGNORECASE)
        for match in matches:
            try:
                if extract_relation_from_group:
                    # Extract relation from group 1 and condition from group_idx
                    relation = match.group(1).lower()
                    condition = match.group(group_idx).strip()
                else:
                    condition = match.group(group_idx).strip()
                
                # Skip if the condition is too short
                if len(condition) <= 3:
                    continue
                
                # Check if condition contains patient pronouns (likely false positive)
                condition_lower = condition.lower()
                if any(term in condition_lower for term in patient_terms):
                    continue
                
                # Check context before the match to avoid matching patient descriptions
                # Look for patient indicators in the 50 characters before the match
                match_start = match.start()
                context_before = text[max(0, match_start - 50):match_start].lower()
                
                # Skip if this appears to be describing the patient
                patient_indicators = ['patient', 'pt', 'he ', 'she ', 'him ', 'her ', 'his ', 'on exam', 'physical exam', 'presenting with']
                if any(indicator in context_before for indicator in patient_indicators):
                    # But allow if there's a clear family history context
                    if 'family history' not in context_before and 'family' not in context_before:
                        continue
                
                family_history.append({
                    "relation": relation,
                    "condition": condition
                })
            except IndexError:
                # Skip if group doesn't exist
                continue
    
    return family_history


def extract_medications(text: str) -> List[Dict[str, str]]:
    """
    Extract medication/drug mentions from text.
    
    Returns a list of dicts with 'drug' and optionally 'route' keys.
    """
    medications = []
    
    # Common medication patterns
    patterns = [
        (r'on ([A-Z][a-z]+(?: [A-Z][a-z]+)*)', 'unknown'),  # "on Aspirin"
        (r'taking ([A-Z][a-z]+(?: [A-Z][a-z]+)*)', 'unknown'),
        (r'prescribed ([A-Z][a-z]+(?: [A-Z][a-z]+)*)', 'unknown'),
        (r'medication: ([A-Z][a-z]+(?: [A-Z][a-z]+)*)', 'unknown'),
        (r'drug: ([A-Z][a-z]+(?: [A-Z][a-z]+)*)', 'unknown'),
        (r'oral ([A-Z][a-z]+(?: [A-Z][a-z]+)*)', 'oral'),
        (r'IV ([A-Z][a-z]+(?: [A-Z][a-z]+)*)', 'intravenous'),
    ]
    
    # Common drug names (basic list - could be expanded)
    common_drugs = [
        'aspirin', 'ibuprofen', 'acetaminophen', 'penicillin', 'amoxicillin',
        'metformin', 'insulin', 'warfarin', 'lisinopril', 'atorvastatin',
        'omeprazole', 'levothyroxine', 'amlodipine', 'metoprolol', 'albuterol'
    ]
    
    for pattern, route in patterns:
        matches = re.finditer(pattern, text, re.IGNORECASE)
        for match in matches:
            try:
                drug = match.group(1).strip()
                # Basic validation - check if it looks like a drug name
                if drug.lower() in common_drugs or len(drug.split()) <= 3:
                    medications.append({
                        "drug": drug,
                        "route": route if route != 'unknown' else None
                    })
            except IndexError:
                # Skip if group doesn't exist
                continue
    
    return medications




def extract_phenotypes(
    text: str,
    nlp,
    matcher: PhraseMatcher,
    phrase_to_ids: Dict[str, Set[str]],
    id_to_label: Dict[str, str],
) -> List[Tuple[str, str, str, int, int, Optional[Dict[str, str]], bool]]:
    """
    Extract phenotype mentions from text using spaCy PhraseMatcher and dependency parsing.

    Returns a list of tuples:
      (phrase, hpo_id, hpo_label, start_char, end_char, onset_info, excluded)
    where onset_info is a dict with 'iso8601duration' or None, and excluded is a boolean
    """
    results: List[Tuple[str, str, str, int, int, Optional[Dict[str, str]], bool]] = []
    seen: Set[Tuple[str, str, int, int]] = set()
    
    # Process text with spaCy
    doc = nlp(text)
    
    # Extract overall age of onset from text
    overall_onset = extract_age_of_onset(text)
    
    # Find matches using PhraseMatcher
    matches = matcher(doc)
    
    # Track which character positions have been matched to avoid overlapping matches
    matched_positions = set()
    
    for match_id, start_token, end_token in matches:
        span = doc[start_token:end_token]
        matched_text = span.text
        start_char = span.start_char
        end_char = span.end_char
        
        # Skip if this position overlaps with a previously matched longer phrase
        if any(start_char < end <= end_char or start_char < start < end_char 
               for start, end in matched_positions):
            continue
        
        norm = normalize_phrase(matched_text)
        if not norm:
            continue
        
        # Get HPO IDs for this normalized phrase
        hpo_ids = phrase_to_ids.get(norm)
        if not hpo_ids:
            continue
        
        # Check if this phenotype is negated using spaCy dependency parsing
        excluded = is_negated_spacy(doc, start_token, end_token)
        
        # Try to find age context near this phenotype mention
        # Look for age mentions within 100 characters before or after
        context_start = max(0, start_char - 100)
        context_end = min(len(text), end_char + 100)
        context = text[context_start:context_end]
        local_onset = extract_age_of_onset(context)
        
        # Use local onset if found, otherwise use overall onset
        onset_info = local_onset if local_onset else overall_onset
        
        for hpo_id in hpo_ids:
            key = (norm, hpo_id, start_char, end_char)
            if key in seen:
                continue
            seen.add(key)
            label = id_to_label.get(hpo_id, "")
            results.append((matched_text, hpo_id, label, start_char, end_char, onset_info, excluded))
            matched_positions.add((start_char, end_char))
    
    # Sort by position in text
    results.sort(key=lambda x: x[3])
    return results


def read_input_text(args: argparse.Namespace) -> str:
    if args.text is not None:
        return args.text
    if args.input_file is not None:
        path = Path(args.input_file)
        if not path.is_file():
            raise SystemExit(f"Input file not found: {path}")
        return path.read_text(encoding="utf-8")
    raise SystemExit("You must provide either --text or --input-file")


def write_results_tsv(
    output_path: Path,
    rows: List[Tuple[str, str, str, int, int, Optional[Dict[str, str]], bool]],
) -> None:
    """
    Write results as a TSV file:
      phrase, hpo_id, hpo_label, start_char, end_char, onset, excluded
    """
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["phrase", "hpo_id", "hpo_label", "start_char", "end_char", "onset", "excluded"])
        for phrase, hpo_id, label, start, end, onset_info, excluded in rows:
            onset_str = onset_info.get("iso8601duration", "") if onset_info else ""
            writer.writerow([phrase, hpo_id, label, start, end, onset_str, excluded])


def create_phenopacket_json(
    rows: List[Tuple[str, str, str, int, int, Optional[Dict[str, str]], bool]],
    text: str,
    id_to_label: Dict[str, str],
) -> Dict:
    """
    Create a PhenoPacket v2 JSON structure from extracted phenotypes.
    
    Returns a dictionary conforming to PhenoPacket schema v2.
    """
    # Extract additional information
    family_history = extract_family_history(text)
    medications = extract_medications(text)
    overall_onset = extract_age_of_onset(text)
    
    # Build phenotypic features
    phenotypic_features = []
    for phrase, hpo_id, hpo_label, start_char, end_char, onset_info, excluded in rows:
        feature = {
            "type": {
                "id": hpo_id,
                "label": hpo_label
            },
            "description": phrase,
            "excluded": excluded
        }
        
        # Add onset if available
        if onset_info:
            feature["onset"] = {
                "age": {
                    "iso8601duration": onset_info.get("iso8601duration")
                }
            }
        
        phenotypic_features.append(feature)
    
    # Build treatments (medications)
    treatments = []
    for med in medications:
        treatment = {
            "agent": {
                "id": f"DRUG:{med['drug'].upper().replace(' ', '_')}",
                "label": med['drug']
            }
        }
        if med.get('route'):
            treatment["routeOfAdministration"] = {
                "id": f"NCIT:{med['route'].upper()}",
                "label": med['route'].title()
            }
        treatments.append(treatment)
    
    # Build phenopacket structure
    phenopacket = {
        "id": f"phenopacket_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "phenotypicFeatures": phenotypic_features,
        "metaData": {
            "created": datetime.now().isoformat() + "Z",
            "createdBy": "phenotype-extractor",
            "phenopacketSchemaVersion": "2.0",
            "resources": [
                {
                    "id": "hp",
                    "name": "Human Phenotype Ontology",
                    "url": "https://hpo.jax.org/",
                    "version": "unknown",
                    "namespacePrefix": "HP",
                    "iriPrefix": "http://purl.obolibrary.org/obo/HP_"
                }
            ]
        }
    }
    
    # Add treatments if any
    if treatments:
        phenopacket["medicalActions"] = [
            {
                "treatment": treatment
            }
            for treatment in treatments
        ]
    
    # Add individual age if available
    if overall_onset:
        phenopacket["subject"] = {
            "timeAtEncounter": {
                "age": {
                    "iso8601duration": overall_onset.get("iso8601duration")
                }
            }
        }
    
    # Add family history as notes (since Family element requires pedigree structure)
    if family_history:
        notes = []
        for fh in family_history:
            notes.append(f"Family history: {fh['relation']} - {fh['condition']}")
        phenopacket["metaData"]["notes"] = notes
    
    return phenopacket


def write_results_json(
    output_path: Path,
    rows: List[Tuple[str, str, str, int, int, Optional[Dict[str, str]], bool]],
    text: str,
    id_to_label: Dict[str, str],
) -> None:
    """
    Write results as a PhenoPacket JSON file.
    """
    phenopacket = create_phenopacket_json(rows, text, id_to_label)
    
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(phenopacket, f, indent=2, ensure_ascii=False)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Extract clinical phenotypes from text and map them to "
            "Human Phenotype Ontology (HPO) terms using local resources only."
        )
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--text",
        type=str,
        help="Paragraph of text to analyze.",
    )
    group.add_argument(
        "--input-file",
        type=str,
        help="Path to a text file containing the paragraph(s) to analyze.",
    )

    parser.add_argument(
        "--hpo-obo",
        type=str,
        required=True,
        help="Path to local HPO .obo file (e.g. hp.obo).",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="phenotypes.tsv",
        help="Path to output file (default: phenotypes.tsv).",
    )
    parser.add_argument(
        "--format",
        type=str,
        choices=["tsv", "json"],
        default="tsv",
        help="Output format: 'tsv' for tab-separated values, 'json' for PhenoPacket JSON (default: tsv).",
    )
    parser.add_argument(
        "--spacy-model",
        type=str,
        default="en_core_web_sm",
        help="Name of local spaCy model to use (default: en_core_web_sm).",
    )
    return parser


def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    hpo_obo_path = Path(args.hpo_obo)
    if not hpo_obo_path.is_file():
        raise SystemExit(f"HPO .obo file not found: {hpo_obo_path}")

    print(f"Loading HPO ontology from {hpo_obo_path} ...")
    phrase_to_ids, id_to_label = parse_hpo_obo(hpo_obo_path)
    print(f"Loaded {len(id_to_label)} HPO terms and {len(phrase_to_ids)} unique phrases.")

    print(f"Loading spaCy model '{args.spacy_model}' ...")
    nlp = load_spacy_model(args.spacy_model)

    print("Building phrase matcher (this may take a moment) ...")
    matcher = build_phrase_matcher(nlp, phrase_to_ids)
    print(f"Built phrase matcher with {len(phrase_to_ids)} phrases.")

    print("Reading input text ...")
    text = read_input_text(args)

    print("Extracting phenotype mentions using spaCy NLP ...")
    rows = extract_phenotypes(text, nlp, matcher, phrase_to_ids, id_to_label)
    print(f"Found {len(rows)} phenotype mentions.")

    output_path = Path(args.output)
    print(f"Writing results to {output_path} ...")
    
    if args.format == "json":
        write_results_json(output_path, rows, text, id_to_label)
        print(f"Generated PhenoPacket JSON with {len(rows)} phenotypic features.")
        family_history = extract_family_history(text)
        medications = extract_medications(text)
        if family_history:
            print(f"  - Found {len(family_history)} family history mentions")
        if medications:
            print(f"  - Found {len(medications)} medication mentions")
    else:
        write_results_tsv(output_path, rows)
        print(f"Generated TSV with {len(rows)} phenotype mentions.")
    
    print("Done.")


if __name__ == "__main__":
    main()

