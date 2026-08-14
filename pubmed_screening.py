#!/usr/bin/env python3

"""Export a live PubMed search to a new Phase 1 screening CSV.

Plain-language overview
-----------------------
1. Ask PubMed which articles match a search (this is the "ESearch" step).
2. Download the details for each match: title, abstract, authors, etc.
   (this is the "EFetch" step).
3. Save everything to a spreadsheet-friendly CSV file you can open in
   Excel, Numbers, or Google Sheets and start screening.

No accounts, API keys, or extra installs are needed - just Python 3.
"""

import argparse
import csv
import os
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime


BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
# NCBI asks that scripts identify themselves with a contact email so they can
# reach you if a script misbehaves. It is optional and never shared publicly.
# Set it with --email, the PUBMED_EMAIL environment variable, or edit this line.
EMAIL = os.environ.get("PUBMED_EMAIL", "your-email@example.com")
TOOL_NAME = "pubmed_phase1_screening_export"
MAX_RESULTS = 10_000
BATCH_SIZE = 100

# Friendly --sort choices mapped to PubMed's own sort values. These match the
# "Sort by" dropdown on the PubMed website.
SORT_OPTIONS = {
    "recent": "date",          # "Most recent" (date added to PubMed). Default.
    "relevance": "relevance",  # "Best match".
    "pubdate": "pub_date",     # "Publication date" (the printed date).
    "author": "Author",        # "First author", A to Z.
    "journal": "JournalName",  # "Journal", A to Z.
}

DEFAULT_QUERY = """
("financial decision making" OR
 "behavioral economics" OR
 "financial exploitation" OR
 "fraud*" OR
 "scam*" OR
 "financial capacity" OR
 "financial literacy" OR
 "financial behavior")
AND
("neuropsychology" OR
 "neuropsych*" OR
 "neuropsychological" OR
 "cognition" OR
 "cognitive" OR
 "cognit*")
AND
("adults" OR
 "Alzheimer's Disease" OR
 "Mild Cognitive Impairment" OR
 "dementia" OR
 "aging")
""".strip()

# Simple mode exports only these three columns, in this order.
SIMPLE_FIELDNAMES = [
    "Authors",
    "Title",
    "Abstract",
]

# Full mode leads with the same three columns, then everything else.
FIELDNAMES = SIMPLE_FIELDNAMES + [
    "PMID",
    "DOI",
    "PubMed URL",
    "Publication Year",
    "Journal",
    "Publication Types",
    "Language",
    "MeSH Terms",
    "Keywords",
    "Screening Decision",
    "Exclusion Reason",
    "Screening Notes",
]


def request_xml(endpoint, parameters, attempts=3, email=EMAIL):
    parameters = {**parameters, "tool": TOOL_NAME, "email": email}
    url = BASE_URL + endpoint + "?" + urllib.parse.urlencode(parameters)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": f"{TOOL_NAME}/1.0 ({email})"},
    )

    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return ET.fromstring(response.read())
        except Exception:
            if attempt == attempts:
                raise
            time.sleep(attempt * 2)


def clean_text(element):
    if element is None:
        return ""
    return " ".join("".join(element.itertext()).split())


def unique_join(values, separator="; "):
    return separator.join(dict.fromkeys(value for value in values if value))


def search_pubmed(query, email=EMAIL, sort="date"):
    root = request_xml(
        "esearch.fcgi",
        {
            "db": "pubmed",
            "term": query,
            "retmode": "xml",
            "retmax": MAX_RESULTS,
            "sort": sort,
        },
        email=email,
    )
    total_count = int(root.findtext("./Count", default="0"))
    pmids = [node.text for node in root.findall("./IdList/Id") if node.text]
    return total_count, pmids


def fetch_articles(pmids, email=EMAIL):
    articles = []
    for start in range(0, len(pmids), BATCH_SIZE):
        batch = pmids[start : start + BATCH_SIZE]
        print(f"Downloading {start + 1}-{start + len(batch)} of {len(pmids)}...")
        root = request_xml(
            "efetch.fcgi",
            {
                "db": "pubmed",
                "id": ",".join(batch),
                "retmode": "xml",
                "rettype": "abstract",
            },
            email=email,
        )
        articles.extend(root.findall("./PubmedArticle"))
        time.sleep(0.34)
    return articles


def parse_authors(citation):
    authors = []
    for author in citation.findall("./Article/AuthorList/Author"):
        group = clean_text(author.find("./CollectiveName"))
        if group:
            authors.append(group)
            continue
        last = clean_text(author.find("./LastName"))
        given = clean_text(author.find("./ForeName")) or clean_text(
            author.find("./Initials")
        )
        name = " ".join(part for part in (given, last) if part)
        if name:
            authors.append(name)
    return unique_join(authors)


def parse_abstract(citation):
    sections = []
    for section in citation.findall("./Article/Abstract/AbstractText"):
        text = clean_text(section)
        label = section.get("Label", "").strip()
        if text:
            sections.append(f"{label}: {text}" if label else text)
    return "\n".join(sections)


def parse_doi(article):
    for article_id in article.findall("./PubmedData/ArticleIdList/ArticleId"):
        if article_id.get("IdType", "").lower() == "doi":
            return clean_text(article_id)
    for location_id in article.findall("./MedlineCitation/Article/ELocationID"):
        if location_id.get("EIdType", "").lower() == "doi":
            return clean_text(location_id)
    return ""


def parse_publication_year(citation):
    pub_date = citation.find("./Article/Journal/JournalIssue/PubDate")
    year = clean_text(pub_date.find("./Year")) if pub_date is not None else ""
    if year:
        return year
    medline_date = clean_text(pub_date.find("./MedlineDate")) if pub_date is not None else ""
    return medline_date[:4] if len(medline_date) >= 4 else medline_date


def parse_mesh_terms(citation):
    terms = []
    for heading in citation.findall("./MeshHeadingList/MeshHeading"):
        descriptor = clean_text(heading.find("./DescriptorName"))
        qualifiers = [clean_text(q) for q in heading.findall("./QualifierName")]
        if descriptor:
            terms.append(
                f"{descriptor} / {', '.join(qualifiers)}" if qualifiers else descriptor
            )
    return unique_join(terms)


def parse_article(article):
    citation = article.find("./MedlineCitation")
    if citation is None:
        return None

    pmid = clean_text(citation.find("./PMID"))
    publication_types = [
        clean_text(node)
        for node in citation.findall("./Article/PublicationTypeList/PublicationType")
    ]
    languages = [
        clean_text(node) for node in citation.findall("./Article/Language")
    ]
    keywords = [
        clean_text(node) for node in citation.findall("./KeywordList/Keyword")
    ]

    return {
        "PMID": pmid,
        "DOI": parse_doi(article),
        "PubMed URL": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
        "Title": clean_text(citation.find("./Article/ArticleTitle")),
        "Abstract": parse_abstract(citation),
        "Authors": parse_authors(citation),
        "Publication Year": parse_publication_year(citation),
        "Journal": clean_text(citation.find("./Article/Journal/Title")),
        "Publication Types": unique_join(publication_types),
        "Language": unique_join(languages),
        "MeSH Terms": parse_mesh_terms(citation),
        "Keywords": unique_join(keywords),
        "Screening Decision": "",
        "Exclusion Reason": "",
        "Screening Notes": "",
    }


def write_csv(articles, output_file, fieldnames=FIELDNAMES):
    rows = [row for article in articles if (row := parse_article(article))]
    with open(output_file, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def ask_year(question, default):
    while True:
        answer = input(f"{question} [{default}]: ").strip()
        if not answer:
            return default
        if answer.isdigit() and len(answer) == 4:
            return int(answer)
        print("  Please enter a 4-digit year, or press Enter for the default.")


def ask_choice(question, default, choices):
    while True:
        answer = input(f"{question} [{default}]: ").strip().lower()
        if not answer:
            return default
        if answer in choices:
            return answer
        print(f"  Please type one of: {', '.join(choices)}")


def ask_yes_no(question, default):
    hint = "Y/n" if default else "y/N"
    while True:
        answer = input(f"{question} [{hint}]: ").strip().lower()
        if not answer:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("  Please answer y or n.")


def run_interactive(args):
    """Set up the export by asking four plain questions."""
    this_year = datetime.now().year
    print("Let's set up your PubMed export. Just four questions.")
    print("Press Enter to accept the [answer] in brackets.\n")

    # 1. The search.
    print("1. Paste your PubMed search below, exactly as it appears in the")
    print("   search box on the PubMed website, then press Enter.")
    query = input("   Search: ").strip()
    if not query:
        query = DEFAULT_QUERY
        print("   (No search entered, using the built-in example search.)")

    # 2. Starting year. We always search through the current year.
    print(f"\n2. From which year onward? (we include everything up to {this_year})")
    start_year = ask_year("   Start year", args.start_year)
    end_year = this_year

    # 3. Sort order.
    print("\n3. What order should the articles be in?")
    print("     recent    - newest first (default)")
    print("     relevance - best match")
    print("     pubdate   - by publication date")
    print("     author    - first author, A to Z")
    print("     journal   - journal name, A to Z")
    sort_key = ask_choice("   Sort by", args.sort, SORT_OPTIONS)

    # 4. Which columns.
    print("\n4. Include all columns (journal, year, DOI, links, screening notes)?")
    print("   Answer No to keep only Authors, Title, and Abstract.")
    all_columns = ask_yes_no("   All columns?", not args.simple)
    simple = not all_columns

    print()
    return query, start_year, end_year, sort_key, simple


def main():
    parser = argparse.ArgumentParser(
        description="Export live PubMed results to a Phase 1 screening CSV."
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=2019,
        help="First publication year to include (default: 2019).",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=datetime.now().year,
        help="Last publication year to include (default: current year).",
    )
    parser.add_argument(
        "--query",
        default=None,
        help="PubMed search. If omitted, the tool asks you step by step.",
    )
    parser.add_argument(
        "--email",
        default=EMAIL,
        help="Contact email sent to NCBI (default: PUBMED_EMAIL env var).",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output CSV path (default: pubmed_screening_<timestamp>.csv).",
    )
    parser.add_argument(
        "--simple",
        action="store_true",
        help="Export only Authors, Title, and Abstract columns.",
    )
    parser.add_argument(
        "--sort",
        choices=SORT_OPTIONS,
        default="recent",
        help="Result order: recent (default), relevance, pubdate, author, journal.",
    )
    args = parser.parse_args()

    # No search given and a real terminal is attached: ask step by step.
    if args.query is None and sys.stdin.isatty():
        search, start_year, end_year, sort_key, simple = run_interactive(args)
    else:
        search = args.query or DEFAULT_QUERY
        start_year, end_year = args.start_year, args.end_year
        sort_key, simple = args.sort, args.simple

    if start_year > end_year:
        parser.error("start year cannot be later than end year")

    query = f"({search}) AND {start_year}:{end_year}[Publication Date]"
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    output_file = args.output or f"pubmed_screening_{timestamp}.csv"

    print("Searching PubMed...")
    total_count, pmids = search_pubmed(
        query, email=args.email, sort=SORT_OPTIONS[sort_key]
    )
    print(f"PubMed reports {total_count} matching articles.")

    if total_count > MAX_RESULTS:
        print(f"Warning: this run will export only the first {MAX_RESULTS} results.")
    if not pmids:
        print("No matching articles were found.")
        return

    articles = fetch_articles(pmids, email=args.email)
    fieldnames = SIMPLE_FIELDNAMES if simple else FIELDNAMES
    count = write_csv(articles, output_file, fieldnames=fieldnames)
    print(f"Done. Wrote {count} articles to {output_file}")


if __name__ == "__main__":
    main()