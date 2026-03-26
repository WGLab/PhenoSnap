### ClinSnap: Clinical phenotype extraction, VCF / ClinVar pathogenic lookup, and digital twin state assembly

This repository provides three utilities:

1. **Phenotype extraction**: Extracts **clinical phenotype mentions** from free text and maps them to **Human Phenotype Ontology (HPO)** terms using only **local resources** (no cloud-based LLMs or APIs). Output can be a TSV file or a PhenoPacket JSON file (conforming to PhenoPacket Schema v2.0) with matched phenotypes, age of onset, family history, and medication information.

2. **VCF / ClinVar pathogenic lookup**: Takes a **VCF file** (GRCh37 or GRCh38 coordinates), queries the **ClinVar** database via NCBI E-utilities, and outputs only variants annotated as **Pathogenic** or **Likely pathogenic**.

3. **Digital twin state assembly**: Reads all available clinical data files (VCF, PhenoPacket JSON) from a designated patient directory and consolidates them into a single **digital twin state JSON file** representing the patient's current clinical picture.

---

### 1. Install dependencies

From the project directory:

```bash
pip install -r requirements.txt
```

Then install a local spaCy English model (only needs to be done once per environment):

```bash
python -m spacy download en_core_web_sm
```

**Note:** The script uses spaCy for advanced NLP capabilities including dependency parsing for accurate negation detection. If you encounter issues downloading the spaCy model, see troubleshooting below.

---

### 2. Download the HPO ontology (.obo)

You need to download the HPO OBO file. Here are several methods:

**Method 1: Direct download via browser**
1. Visit: https://github.com/obophenotype/human-phenotype-ontology/releases/latest
2. Look for the latest release and download `hp.obo` (or `hp-base.obo`)
3. Alternatively, direct download link: https://github.com/obophenotype/human-phenotype-ontology/raw/master/hp.obo
4. Save the file to your project directory or a convenient location (e.g., `C:\data\hp.obo` or `./hp.obo`)

**Method 2: Download using PowerShell (Windows)**
```powershell
# Download to current directory
Invoke-WebRequest -Uri "https://github.com/obophenotype/human-phenotype-ontology/raw/master/hp.obo" -OutFile "hp.obo"

# Or download to a specific location
Invoke-WebRequest -Uri "https://github.com/obophenotype/human-phenotype-ontology/raw/master/hp.obo" -OutFile "C:\data\hp.obo"
```

**Method 3: Download using curl (Windows/Linux/macOS)**
```bash
# Download to current directory
curl -L -o hp.obo "https://github.com/obophenotype/human-phenotype-ontology/raw/master/hp.obo"

# Or download to a specific location
curl -L -o C:\data\hp.obo "https://github.com/obophenotype/human-phenotype-ontology/raw/master/hp.obo"
```

**Method 4: Download using Python script (easiest)**
```bash
# Use the included helper script
python download_hpo.py --output hp.obo

# Or specify a custom location
python download_hpo.py --output C:\data\hp.obo
```

**Method 5: Download using Python code**
```python
import urllib.request
urllib.request.urlretrieve(
    "https://github.com/obophenotype/human-phenotype-ontology/raw/master/hp.obo",
    "hp.obo"
)
print("Downloaded hp.obo successfully!")
```

**Note:** The file is typically around 50-100 MB in size, so the download may take a minute or two depending on your internet connection.

---

### 3. Phenotype extraction

You can either pass a paragraph directly via `--text` or use an input file via `--input-file`.

**Output formats:**
- `--format tsv` (default): Tab-separated values file
- `--format json`: PhenoPacket JSON file (includes age of onset, family history, medications)

- **Using `--text` with TSV output:**

```bash
python extract_phenotypes.py ^
  --text "The patient has short stature and developmental delay." ^
  --hpo-obo path\to\hp.obo ^
  --output phenotypes.tsv ^
  --format tsv
```

- **Using `--input-file` with JSON output:**

```bash
python extract_phenotypes.py ^
  --input-file example_input.txt ^
  --hpo-obo path\to\hp.obo ^
  --output phenotypes.json ^
  --format json
```

On Unix-like systems (Linux/macOS), the same commands look like:

```bash
python extract_phenotypes.py \
  --text "The patient has short stature and developmental delay." \
  --hpo-obo path/to/hp.obo \
  --output phenotypes.tsv \
  --format tsv
```

---

### 4. Phenotype extraction output formats

#### TSV Format (default)

The TSV output file contains tab-separated values with header:

- **phrase**: the surface text of the phenotype mention in the paragraph
- **hpo_id**: the matched HPO identifier (e.g. `HP:0004322`)
- **hpo_label**: the primary HPO label for that ID
- **start_char**: character offset (0-based) where the mention starts in the input text
- **end_char**: character offset (0-based, exclusive) where the mention ends in the input text
- **onset**: ISO 8601 duration format for age of onset (e.g., `P14M` for 14 months), if detected
- **excluded**: boolean indicating if the phenotype is negated/excluded (e.g., "No history of seizures" → `True`)

Example `phenotypes.tsv`:

```text
phrase	hpo_id	hpo_label	start_char	end_char	onset	excluded
short stature	HP:0004322	Short stature	16	29	P14M	False
developmental delay	HP:0001263	Developmental delay	34	52	P14M	False
seizures	HP:0001250	Seizure	123	131		True
```

#### PhenoPacket JSON Format

The JSON output conforms to **PhenoPacket Schema v2.0** and includes:

- **phenotypicFeatures**: Array of phenotypic features with HPO terms
  - Each feature includes HPO ID, label, description, and optional onset (age of onset)
- **medicalActions**: Array of treatments/medications if detected in text
  - Includes drug name and route of administration
- **subject**: Patient age information if age of onset is detected
- **metaData**: Metadata including creation timestamp, schema version, and ontology resources
- **metaData.notes**: Family history mentions if detected

Example `phenotypes.json` structure:

```json
{
  "id": "phenopacket_20260220_123456",
  "phenotypicFeatures": [
    {
      "type": {
        "id": "HP:0004322",
        "label": "Short stature"
      },
      "description": "short stature",
      "excluded": false,
      "onset": {
        "age": {
          "iso8601duration": "P14M"
        }
      }
    },
    {
      "type": {
        "id": "HP:0001250",
        "label": "Seizure"
      },
      "description": "seizures",
      "excluded": true
    }
  ],
  "medicalActions": [
    {
      "treatment": {
        "agent": {
          "id": "DRUG:ASPIRIN",
          "label": "Aspirin"
        },
        "routeOfAdministration": {
          "id": "NCIT:ORAL",
          "label": "Oral"
        }
      }
    }
  ],
  "subject": {
    "timeAtEncounter": {
      "age": {
        "iso8601duration": "P14M"
      }
    }
  },
  "metaData": {
    "created": "2026-02-20T12:34:56Z",
    "createdBy": "phenotype-extractor",
    "phenopacketSchemaVersion": "2.0",
    "resources": [...],
    "notes": ["Family history: maternal - diabetes"]
  }
}
```

**Extracted Information:**
- **Age of onset**: Automatically extracted from phrases like "14-month-old", "at age 2 years"
- **Family history**: Detected from phrases like "family history of...", "maternal...", "paternal..."
- **Medications**: Detected from phrases like "on Aspirin", "taking medication", "oral Metformin"

---

### 5. Phenotype extraction notes and limitations

- **Local only**: the script uses spaCy NLP and a local HPO OBO file; no calls to remote LLMs or web APIs are made during extraction.
- **NLP-based matching**: extraction uses spaCy's PhraseMatcher for accurate phrase matching against HPO labels and synonyms, with dependency parsing for negation detection.
- **Negation detection**: uses spaCy's dependency parsing to accurately detect negated phenotypes (e.g., "No history of seizures") by analyzing the dependency tree structure.
- **Performance**: building the phrase matcher can take a bit of time on first run, since it processes all HPO terms and synonyms. The script prioritizes longer phrases to avoid partial matches.
- **Age of onset extraction**: Uses pattern matching to detect common age expressions (e.g., "14-month-old", "at age 2 years"). May not capture all variations.
- **Family history extraction**: Basic pattern matching for common family history phrases. More complex family structures may require manual annotation.
- **Medication extraction**: Detects common medication patterns but may miss less common drug names or misspelled medications.
- **PhenoPacket compliance**: The JSON output conforms to PhenoPacket Schema v2.0 and can be validated using PhenoPacket validation tools.

---

### 6. VCF / ClinVar pathogenic variant lookup

The script **`vcf_clinvar_pathogenic.py`** reads a VCF file (GRCh37 or GRCh38), converts each variant to SPDI format, queries the **ClinVar** database via NCBI E-utilities, and writes only variants that are classified as **Pathogenic** or **Likely pathogenic** to a TSV file.

**Dependencies:** The script uses the `requests` library (included in `requirements.txt`). No HPO or spaCy model is required for this script.

#### Run the script

```bash
python vcf_clinvar_pathogenic.py --vcf input.vcf --out hits.tsv --assembly GRCh38
```

**Arguments:**

- **`--vcf`** (required): Path to the input VCF file.
- **`--out`** (required): Path to the output TSV file.
- **`--assembly`**: Reference assembly: `GRCh38` (default) or `GRCh37`.

**Example (Windows):**

```powershell
python vcf_clinvar_pathogenic.py --vcf variants.vcf --out clinvar_hits.tsv --assembly GRCh38
```

**Example (Linux/macOS):**

```bash
python vcf_clinvar_pathogenic.py --vcf variants.vcf --out clinvar_hits.tsv --assembly GRCh37
```

#### Output format

The output is a tab-separated file with header:

| Column           | Description                                      |
|------------------|--------------------------------------------------|
| CHROM            | Chromosome (from VCF)                            |
| POS              | Position (1-based)                              |
| REF              | Reference allele                                |
| ALT              | Alternate allele                                 |
| ClinVarID        | ClinVar variation ID                             |
| Significance     | Clinical significance (e.g. Pathogenic, Likely pathogenic) |
| ReviewStatus     | ClinVar review status                            |

Only variants that have at least one ClinVar record with Pathogenic or Likely pathogenic significance are included.

#### Notes and limitations (VCF / ClinVar script)

- **Network required**: The script queries NCBI E-utilities (ClinVar) over the internet.
- **Rate limiting**: Requests are throttled to about 3 per second to comply with NCBI usage guidelines; processing large VCFs can take time.
- **SPDI-based lookup**: Variants are converted to SPDI (Sequence, Position, Deletion, Insertion) using RefSeq accessions for the chosen assembly. Unrecognized chromosomes are skipped.
- **Multi-allelic sites**: Each alternate allele is queried separately.

---

### 7. Digital twin state assembly

The script **`rdmdt_assemble.py`** reads all available clinical data files from a designated patient directory and consolidates them into a single JSON file representing the current state of the patient's digital twin.

**Dependencies:** No additional dependencies beyond the Python standard library are required.

#### Run the script

```bash
python rdmdt_assemble.py --input-dir ./patient_data --out twin_state.json
```

**Arguments:**

- **`--input-dir`** (required): Path to the patient data directory containing the latest clinical files.
- **`--out`** (required): Path to the output JSON file.

#### Supported input file types

The script automatically detects files by extension within the input directory:

| Extension | Data type | Source |
|-----------|-----------|--------|
| `*.vcf` | Genotype data (variants, reference assembly) | Whole-exome or whole-genome sequencing |
| `*.json` | PhenoPacket (HPO terms, medications, family history) | ClinSnap phenotype extraction output |

If multiple files of the same type exist, the last file (alphabetically sorted) is used. Components for which no file is found are set to `null` in the output, allowing the digital twin to be instantiated even when only partial data is available.

#### Output format

The output is a single JSON file with the following structure:

```json
{
  "assembled_at": "2026-03-15T18:52:53.498742+00:00",
  "genotype": {
    "reference_assembly": "GRCh38",
    "variants": [
      {
        "chrom": "chr6",
        "pos": 65057613,
        "ref": "C",
        "alt": "T",
        "genotype": "0/1"
      }
    ]
  },
  "phenotype": {
    "created": "2026-02-20T11:52:37.171517Z",
    "phenotypic_features": [
      {
        "hpo_id": "HP:0001263",
        "hpo_label": "Global developmental delay",
        "excluded": false,
        "onset": "P14M"
      }
    ],
    "medications": ["metoprolol"],
    "notes": ["Family history: father - arrhythmia"],
    "subject": {
      "timeAtEncounter": {
        "age": { "iso8601duration": "P14M" }
      }
    }
  }
}
```

#### Usage with PhenoSkill and GenoSkill

In the AADT framework, the patient directory serves as the shared workspace for the digital twin. When PhenoSkill generates a new PhenoPacket file (Case Study 1) or GenoSkill detects a ClinVar variant reclassification and updates the VCF annotations (Case Study 2), the corresponding file in the patient directory is overwritten. Running `rdmdt_assemble.py` after any such update produces a new digital twin state reflecting the latest clinical picture.

```bash
# After PhenoSkill extracts new phenotypes
python rdmdt_assemble.py --input-dir ./patient_data --out twin_state.json

# After GenoSkill detects a ClinVar reclassification
python rdmdt_assemble.py --input-dir ./patient_data --out twin_state.json
```

#### Notes and limitations (digital twin assembly)

- **Local only**: The script reads files from disk and writes output locally. No network access is required.
- **Last-file-wins**: If multiple files of the same type exist in the input directory, the last file (sorted alphabetically) is used. This supports the overwrite-based update model used by PhenoSkill and GenoSkill.
- **Partial instantiation**: Missing data types result in `null` values in the output rather than errors, allowing the digital twin to be created with incomplete data.
- **No validation**: The script does not validate the clinical correctness of input data. It assembles whatever files are present in the directory.
