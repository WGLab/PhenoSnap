#!/usr/bin/env python3
"""
Helper script to download the HPO .obo file.
"""

import argparse
import sys
from pathlib import Path
import urllib.request
from urllib.error import URLError


def download_hpo_obo(output_path: Path, url: str = None):
    """
    Download the HPO .obo file from the official repository.
    
    Args:
        output_path: Path where to save the downloaded file
        url: Optional custom URL (defaults to official HPO GitHub raw URL)
    """
    if url is None:
        url = "https://github.com/obophenotype/human-phenotype-ontology/raw/master/hp.obo"
    
    output_path = Path(output_path)
    
    print(f"Downloading HPO .obo file from: {url}")
    print(f"Saving to: {output_path.absolute()}")
    
    try:
        # Create parent directories if they don't exist
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Download with progress indication
        def show_progress(block_num, block_size, total_size):
            downloaded = block_num * block_size
            percent = min(downloaded * 100 / total_size, 100) if total_size > 0 else 0
            print(f"\rProgress: {percent:.1f}% ({downloaded / (1024*1024):.1f} MB)", end="", flush=True)
        
        urllib.request.urlretrieve(url, output_path, reporthook=show_progress)
        print("\nDownload completed successfully!")
        
        # Verify file was downloaded
        if output_path.exists() and output_path.stat().st_size > 0:
            size_mb = output_path.stat().st_size / (1024 * 1024)
            print(f"File size: {size_mb:.2f} MB")
            return True
        else:
            print("Error: Downloaded file appears to be empty or doesn't exist.", file=sys.stderr)
            return False
            
    except URLError as e:
        print(f"\nError downloading file: {e}", file=sys.stderr)
        print("\nTroubleshooting:")
        print("1. Check your internet connection")
        print("2. Verify the URL is accessible: https://github.com/obophenotype/human-phenotype-ontology")
        print("3. Try downloading manually using a web browser")
        return False
    except Exception as e:
        print(f"\nUnexpected error: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Download the Human Phenotype Ontology (HPO) .obo file."
    )
    parser.add_argument(
        "--output",
        type=str,
        default="hp.obo",
        help="Path where to save the downloaded file (default: hp.obo)",
    )
    parser.add_argument(
        "--url",
        type=str,
        default=None,
        help="Custom URL to download from (defaults to official HPO repository)",
    )
    
    args = parser.parse_args()
    
    success = download_hpo_obo(args.output, args.url)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
