import argparse
import codecs
import json
import logging
import os
from pathlib import Path
import json
from pathlib import Path
import pdfplumber  # or PyPDF2
from bs4 import BeautifulSoup

from nlm_ingestor.ingestor import table_parser, visual_ingestor
from nlm_ingestor.ingestor.pdf_ingestor import PDFIngestor

TEST_COVERAGE_RATIO = 0.93  # Minimum coverage to pass the test
# Set up logging
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


def save_text_content(doc_id, text_content, text_type):
    """Save text content to file"""
    # Create text directory if it doesn't exist
    text_dir = Path("files/text")
    text_dir.mkdir(parents=True, exist_ok=True)

    # Save text file
    output_path = text_dir / f"{doc_id}_{text_type}.txt"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(text_content)


def load_text_content(doc_id, text_type):
    """Load text content from file if it exists"""
    text_path = Path(f"files/text/{doc_id}_{text_type}.txt")
    if text_path.exists():
        with open(text_path, "r", encoding="utf-8") as f:
            return f.read()
    return None


def get_pdf_text_baseline(pdf_path):
    """Extract text from PDF using pdfplumber as baseline"""
    text_content = []
    page_lookup = {}  # Dictionary to store word -> page_number mapping

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):  # Start page numbers at 1
            text = page.extract_text()

            # Add space between any letter followed by a capital letter
            normalized_text = ""
            for i in range(len(text) - 1):
                normalized_text += text[i]
                if (
                    text[i].isalpha()
                    and text[i + 1].isupper()
                    and not text[i].isupper()
                ):  # Don't split acronyms
                    normalized_text += " "
            normalized_text += text[-1] if text else ""

            # Store page number for each word
            for word in normalized_text.split():
                page_lookup[word.lower()] = page_num

            text_content.append(normalized_text.strip())

    return "\n".join(text_content), page_lookup


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


def compare_text_content(baseline_text, ingestor_text, page_lookup=None):
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

    # Create missing words with page numbers
    missing_words_with_pages = []
    for word in baseline_words - ingestor_words:
        page_num = page_lookup.get(word, "unknown") if page_lookup else "unknown"
        missing_words_with_pages.append((word, page_num))

    return {
        "coverage": coverage,
        "total_baseline_words": len(baseline_words),
        "total_ingestor_words": len(ingestor_words),
        "words_found": len(words_found),
        "missing_words": missing_words_with_pages,
    }


def run_test(doc_id=""):
    """Run the test on a single document or all documents in the pdf directory"""
    if doc_id:
        pdfs = [doc_id]
    else:
        pdf_dir = "files/pdf"
        pdfs = [Path(f).stem for f in os.listdir(pdf_dir) if f.endswith(".pdf")]

    # Create debug directory if it doesn't exist
    debug_dir = Path("files/debug")
    debug_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for pdf_id in pdfs:
        try:
            logger.info(f"Processing document: {pdf_id}")
            pdf_path = f"files/pdf/{pdf_id}.pdf"

            # Try to load cached baseline text, otherwise extract and save
            baseline_text = load_text_content(pdf_id, "baseline")
            if baseline_text is None:
                logger.info("Getting baseline text...")
                baseline_text, page_lookup = get_pdf_text_baseline(pdf_path)
                save_text_content(pdf_id, baseline_text, "baseline")
            else:
                logger.info("Using cached baseline text")
                # Get fresh page_lookup even with cached text
                _, page_lookup = get_pdf_text_baseline(pdf_path)
            logger.debug(f"Baseline text length: {len(baseline_text)}")

            # Always get fresh ingestor text
            logger.info("Getting ingestor text...")
            ingestor_text = get_ingestor_text(pdf_id)
            logger.debug(f"Ingestor text length: {len(ingestor_text)}")

            # Save debug output
            debug_file = debug_dir / f"{pdf_id}_comparison.txt"
            with open(debug_file, "w", encoding="utf-8") as f:
                f.write("=== BASELINE TEXT ===\n")
                f.write(baseline_text)
                f.write("\n\n=== INGESTOR TEXT ===\n")
                f.write(ingestor_text)
                f.write("\n\n=== STATISTICS ===\n")
                f.write(f"Baseline text length: {len(baseline_text)}\n")
                f.write(f"Ingestor text length: {len(ingestor_text)}\n")

            # Compare results
            comparison = compare_text_content(baseline_text, ingestor_text, page_lookup)
            results.append((pdf_id, comparison))

            # Log detailed results
            logger.info(f"Results for {pdf_id}:")
            logger.info(f"Text coverage: {comparison['coverage']*100:.2f}%")
            logger.info(f"Baseline words: {comparison['total_baseline_words']}")
            logger.info(f"Ingestor words: {comparison['total_ingestor_words']}")
            logger.info(f"Words found: {comparison['words_found']}")

            # Add comparison stats to debug file
            with open(debug_file, "a", encoding="utf-8") as f:
                f.write(f"\nCoverage: {comparison['coverage']*100:.2f}%\n")
                f.write(f"Baseline words: {comparison['total_baseline_words']}\n")
                f.write(f"Ingestor words: {comparison['total_ingestor_words']}\n")
                f.write(f"Words found: {comparison['words_found']}\n")

            # Log missing words if any
            if comparison["missing_words"]:
                # Sort missing words by length and get 10 longest
                longest_missing = sorted(
                    comparison["missing_words"],
                    key=lambda x: len(x[0]),  # Sort by word length, not page number
                    reverse=True,
                )[:10]

                logger.info("Sample of longest missing words/phrases:")
                # Add missing words to debug file
                with open(debug_file, "a", encoding="utf-8") as f:
                    f.write("\n=== LONGEST MISSING WORDS ===\n")
                    for i, (word, page_num) in enumerate(longest_missing, 1):
                        msg = f"{i}. (Page {page_num}, {len(word)} chars) {word}"
                        logger.info(msg)
                        f.write(f"{msg}\n")

            # Assert that the coverage is over 93%
            assert (
                comparison["coverage"] > TEST_COVERAGE_RATIO
            ), f"Text coverage for {pdf_id} is below {TEST_COVERAGE_RATIO*100}%: {comparison['coverage']*100:.2f}%"

        except Exception as e:
            logger.error(f"Error processing {pdf_id}: {str(e)}", exc_info=True)
            results.append((pdf_id, {"error": str(e)}))

            # Log error to debug file
            with open(debug_file, "a", encoding="utf-8") as f:
                f.write("\n=== ERROR ===\n")
                f.write(str(e))

    return results

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
