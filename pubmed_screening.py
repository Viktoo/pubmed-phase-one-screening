#!/usr/bin/env python3

"""Export a live PubMed search to a new Phase 1 screening CSV."""

import argparse
import csv
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime


BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
EMAIL = "your-email@example.com"  # Replace once with your email address.
TOOL_NAME = "pubmed_phase1_screening_export"
MAX_RESULTS = 10_000
BATCH_SIZE = 100

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

FIELDNAMES = [
    "PMID",
    "DOI",
    "PubMed URL",
    "Title",
    "Abstract",
    "Authors",
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


def request_xml(endpoint, parameters, attempts=3):
    parameters = {**parameters, "tool": TOOL_NAME, "email": EMAIL}
    url = BASE_URL + endpoint + "?" + urllib.parse.urlencode(parameters)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": f"{TOOL_NAME}/1.0 ({EMAIL})"},
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


def search_pubmed(query):
    root = request_xml(
        "esearch.fcgi",
        {
            "db": "pubmed",
            "term": query,
            "retmode": "xml",
            "retmax": MAX_RESULTS,
            "sort": "pub date",
        },
    )
    total_count = int(root.findtext("./Count", default="0"))
    pmids = [node.text for node in root.findall("./IdList/Id") if node.text]
    return total_count, pmids


def fetch_articles(pmids):
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


def write_csv(articles, output_file):
    rows = [row for article in articles if (row := parse_article(article))]
    with open(output_file, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


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
        default=DEFAULT_QUERY,
        help="Optional custom PubMed query (default: embedded review query).",
    )
    args = parser.parse_args()

    if args.start_year > args.end_year:
        parser.error("--start-year cannot be later than --end-year")

    query = (
        f"({args.query}) AND "
        f"{args.start_year}:{args.end_year}[Publication Date]"
    )
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    output_file = f"pubmed_screening_{timestamp}.csv"

    print("Searching PubMed...")
    total_count, pmids = search_pubmed(query)
    print(f"PubMed reports {total_count} matching articles.")

    if total_count > MAX_RESULTS:
        print(f"Warning: this run will export only the first {MAX_RESULTS} results.")
    if not pmids:
        print("No matching articles were found.")
        return

    articles = fetch_articles(pmids)
    count = write_csv(articles, output_file)
    print(f"Done. Wrote {count} articles to {output_file}")


if __name__ == "__main__":
    main()