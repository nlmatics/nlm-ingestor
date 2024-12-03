import argparse
import codecs
import json
import logging
import os
from pathlib import Path

import pdfplumber  # or PyPDF2
from bs4 import BeautifulSoup

from nlm_ingestor.ingestor import table_parser, visual_ingestor
from nlm_ingestor.ingestor.pdf_ingestor import PDFIngestor

# Set up logging
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


def get_pdf_text_baseline(pdf_path):
    """Extract text from PDF using pdfplumber as baseline"""
    text_content = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            text_content.append(text.strip())

    return "\n".join(text_content)


def get_ingestor_text(doc_id):
    """Get text from PDFIngestor"""
    pdf_file = f"files/pdf/{doc_id}.pdf"

    if not os.path.isfile(pdf_file):
        raise FileNotFoundError(f"PDF file {pdf_file} not found")

    logger.info(f"Processing PDF with ingestor: {pdf_file}")

    parse_options = {
        "apply_ocr": False,
        "use_new_indent_parser": True,
        "render_format": "all",
    }

    ingestor = PDFIngestor(pdf_file, parse_options)

    # Extract text from blocks
    text_content = []
    for block in ingestor.blocks:
        if block.get("block_text"):
            text_content.append(block["block_text"].strip())

    return "\n".join(text_content)


def compare_text_content(baseline_text, ingestor_text):
    """Compare text content between baseline and ingestor"""

    # Normalize text for comparison
    def normalize_text(text):
        return " ".join(text.lower().split())

    baseline_normalized = normalize_text(baseline_text)
    ingestor_normalized = normalize_text(ingestor_text)

    # Get words from each text
    baseline_words = set(baseline_normalized.split())
    ingestor_words = set(ingestor_normalized.split())

    # Calculate coverage
    words_found = baseline_words.intersection(ingestor_words)
    coverage = len(words_found) / len(baseline_words) if baseline_words else 0

    return {
        "coverage": coverage,
        "total_baseline_words": len(baseline_words),
        "total_ingestor_words": len(ingestor_words),
        "words_found": len(words_found),
        "missing_words": baseline_words - ingestor_words,
    }


def run_test(doc_id=""):
    """Run the test on a single document or all documents in the pdf directory"""
    if doc_id:
        pdfs = [doc_id]
    else:
        pdf_dir = "files/pdf"
        pdfs = [Path(f).stem for f in os.listdir(pdf_dir) if f.endswith(".pdf")]

    results = []
    for pdf_id in pdfs:
        try:
            logger.info(f"Processing document: {pdf_id}")
            pdf_path = f"files/pdf/{pdf_id}.pdf"

            # Get baseline text
            logger.info("Getting baseline text...")
            baseline_text = get_pdf_text_baseline(pdf_path)
            logger.debug(f"Baseline text length: {len(baseline_text)}")

            # Get ingestor text
            logger.info("Getting ingestor text...")
            ingestor_text = get_ingestor_text(pdf_id)
            logger.debug(f"Ingestor text length: {len(ingestor_text)}")

            # Compare results
            comparison = compare_text_content(baseline_text, ingestor_text)
            results.append((pdf_id, comparison))

            logger.info(f"Results for {pdf_id}:")
            logger.info(f"Text coverage: {comparison['coverage']*100:.2f}%")
            logger.info(f"Baseline words: {comparison['total_baseline_words']}")
            logger.info(f"Ingestor words: {comparison['total_ingestor_words']}")
            logger.info(f"Words found: {comparison['words_found']}")
            if comparison["missing_words"]:
                # Sort missing words by length and get 10 longest
                longest_missing = sorted(
                    comparison["missing_words"], key=len, reverse=True
                )[:10]

                logger.info("Sample of longest missing words/phrases:")
                for i, word in enumerate(longest_missing, 1):
                    logger.info(f"{i}. ({len(word)} chars) {word}")

        except Exception as e:
            logger.error(f"Error processing {pdf_id}: {str(e)}", exc_info=True)
            results.append((pdf_id, {"error": str(e)}))

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test PDF text extraction")
    parser.add_argument(
        "--doc_id", help="Specific document ID to process", nargs="+", default=""
    )
    args = parser.parse_args()

    doc_id = "_".join(args.doc_id) if args.doc_id else ""

    print(f"Running test for document: {doc_id or 'all documents'}")
    results = run_test(doc_id=doc_id)

    # Print summary
    print("\nTest Summary:")
    print("=" * 80)
    for doc_id, result in results:
        print(f"\nDocument: {doc_id}")
        if "error" in result:
            print(f"Error: {result['error']}")
        else:
            print(f"Coverage: {result['coverage']*100:.2f}%")
            print(
                f"Words found: {result['words_found']} of {result['total_baseline_words']}"
            )
