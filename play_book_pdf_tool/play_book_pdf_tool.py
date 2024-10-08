import os
import pathlib
import unicodedata
from operator import itemgetter
import datetime
import json
import logging
import re
import html

import click
from pikepdf import Pdf, OutlineItem
import img2pdf
from pydash import _

logging.basicConfig(format="[%(levelname)s] %(message)s")
logging.getLogger().setLevel(logging.INFO)


@click.command()
@click.argument(
    "book-base-path",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, writable=True,
                    readable=True, path_type=pathlib.Path),
)
def pdf_generate(book_base_path: pathlib.Path):
    """Build a PDF from the Google Play Book pages located in the directory BOOK-BASE-PATH.

    Example: play-book-pdf-build "books/BwCMEAAAQBAJ"

    Note: the pages of the book need to have already been downloaded prior to running this command.
    """

    try:
        with open(f"{book_base_path}/manifest.json") as f_manifest:
            manifest = json.load(f_manifest)
    except FileNotFoundError:
        logging.error(
            f"Couldn't find [{f'{book_base_path}/manifest.json'}]! Aborting...")
        raise

    pages_filename = pathlib.Path(book_base_path / "pages.txt").read_text(
        encoding="UTF-8").splitlines()

    if manifest.get("is_right_to_left"):
        logging.info(
            "the manifest indicates that the book pages are ordered right to left. We will swap the order of the pages so that they show correctly in the PDF."
        )

        front = _.head(pages_filename)
        back = _.last(pages_filename)

        reversed_middle = _(pages_filename).initial().tail().chunk(2).map(
            _.reverse).flatten()

        pages_filename = reversed_middle.unshift(front).push(back).value()

    page_paths = list(map(lambda fn: str(book_base_path / fn), pages_filename))

    print(f"Merging {len(page_paths)} pages... (this can take a long time)")

    tmp_pdf = book_base_path / "book-tmp.pdf"
    create_pdf(page_paths, tmp_pdf)

    print("Adding the metadata and the table of contents...")
    with Pdf.open(tmp_pdf) as pdf:
        add_metadata(book_base_path, pdf)
        add_toc(book_base_path, pdf)

        filename = generate_output_pdf_filename(book_base_path)
        output_pdf = book_base_path / filename
        pdf.save(str(output_pdf), linearize=True)

        tmp_pdf.unlink()

        print(f'Done! PDF saved to "{str(output_pdf)}"')


def create_pdf(image_paths, output_pdf_path):
    for path in image_paths:
        if os.path.getsize(path) == 0:
            raise f"image at path [{path}] is empty"
        # test-read a byte from it so that we can abort early in case
        # we cannot read data from the file
        with open(path, "rb") as im:
            im.read(1)

    output_pdf = open(output_pdf_path, "wb")
    img2pdf.convert(*image_paths, outputstream=output_pdf)


def generate_output_pdf_filename(base_path):
    try:
        with open(f"{base_path}/manifest.json") as f_manifest:
            manifest = json.load(f_manifest)
    except FileNotFoundError:
        logging.error(f"Couldn't find [{f'{base_path}/manifest.json'}]! Aborting...")
        raise

    m = _(manifest)

    title = m.get("metadata.title").apply(html.unescape).value()
    year = m.get("metadata.pub_date").split(".").head().value()
    authors = m.get("metadata.authors").apply(html.unescape).value()

    filename = f"{title} ({year}) — {authors}"
    return to_valid_filename(filename) + ".pdf"


def add_metadata(base_path, pdf):
    try:
        with open(f"{base_path}/manifest.json") as f_manifest:
            manifest = json.load(f_manifest)
    except FileNotFoundError:
        logging.error(f"Couldn't find [{f'{base_path}/manifest.json'}]! Aborting...")
        raise

    with pdf.open_metadata() as pdf_metadata:
        m = _(manifest)

        pdf_metadata["dc:title"] = m.get("metadata.title").apply(html.unescape).value()

        if authors := m.get("metadata.authors").value():
            pdf_metadata["dc:creator"] = [html.unescape(author).strip() for author in
                                          authors.split(",")]

        if publisher := m.get("metadata.publisher").value():
            pdf_metadata["dc:publisher"] = [publisher]

        if pub_date := m.get("metadata.pub_date").value():
            xmp_date = pub_date.replace(".", "-", 3)

            if validate_xmp_date(xmp_date):
                pdf_metadata["xmp:CreateDate"] = xmp_date
            else:
                logging.warning(
                    f"Invalid xmp:CreateDate format '{xmp_date}'. Metadata will not include 'xmp:CreateDate'. See https://developer.adobe.com/xmp/docs/XMPNamespaces/XMPDataTypes/#date"
                )
        # Unused properties:
        #   metadata
        #       .num_pages
        #       .preview
        #       .volume_id

        if language := m.get("language").value():
            pdf_metadata["dc:language"] = [language]

        # Unused properties:
        #   volume_version
        #   first_chapter_start_page
        #   preferred_mode
        #   available_mode
        #   default_size
        #       .width
        #       .height
        #   image_mode_positions
        #       .content_start
        #       .content_end
        #   text_mode_positions
        #       .content_start
        #       .content_end
        #


def add_toc(book_base_path, pdf):
    try:
        with open(book_base_path / "toc.json") as f_toc:
            toc = json.load(f_toc)
    except FileNotFoundError:
        logging.error(
            "Couldn't find toc.json! Falling back to manifest.json. The outline structure will be flat...")
        try:
            with open(book_base_path / "manifest.json") as f_toc:
                toc = json.load(f_toc)["toc_entry"]
        except FileNotFoundError:
            logging.error("Couldn't find manifest.json either! Aborting...")
            raise

    if toc is None or len(toc) == 0:
        raise "No table of contents or no entries"

    with pdf.open_outline() as pdf_outline:
        pdf_outline.root.clear()

        for toc_item in toc:
            label, depth, page_index = itemgetter("label", "depth", "page_index")(
                toc_item)
            label = html.unescape(label)

            parent = pdf_outline.root
            for __ in range(depth):
                parent = parent[-1].children

            outline_item = OutlineItem(html.unescape(label), page_index)
            parent.append(outline_item)


def to_valid_filename(value):
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"[^\w\s\-.,—()]", "", value).strip("-_")
    return value


def validate_xmp_date(date_str):
    # https://developer.adobe.com/xmp/docs/XMPNamespaces/XMPDataTypes/#date
    formats = [
        "%Y",  # YYYY
        "%Y-%m",  # YYYY-MM
        "%Y-%m-%d",  # YYYY-MM-DD
        "%Y-%m-%dT%H:%M%z",  # YYYY-MM-DDThh:mmTZD (TZD as UTC offset)
        "%Y-%m-%dT%H:%M:%S%z",  # YYYY-MM-DDThh:mm:ssTZD (TZD as UTC offset)
        # "%Y-%m-%dT%H:%M:%S.%f%z"  # FIXME: strptime cannot handle the fractional second part so this last format is not possible. Will need to add a workaround for that one if we need to support this format at a later point.
    ]

    for fmt in formats:
        try:
            datetime.datetime.strptime(date_str, fmt)
            return True
        except ValueError:
            continue

    return False


if __name__ == "__main__":
    pdf_generate()
