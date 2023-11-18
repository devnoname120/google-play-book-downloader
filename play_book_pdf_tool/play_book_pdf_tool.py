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


@click.command()
@click.argument('book-base-path',
                type=click.Path(exists=True, file_okay=False, dir_okay=True, writable=True, readable=True,
                                path_type=pathlib.Path))
def pdf_generate(book_base_path: pathlib.Path):
    """Build a PDF from the Google Play Book pages located in the directory BOOK-BASE-PATH.

    Example: play-book-pdf-build "books/BwCMEAAAQBAJ"

    Note: the pages of the book need to have already been downloaded prior to running this command.
    """

    pages_filename = book_base_path / 'pages.txt'

    pages_filename = pathlib.Path(pages_filename).read_text(encoding='UTF-8').splitlines()
    page_paths = list(map(lambda fn: str(book_base_path / fn), pages_filename))

    print(f'Merging {len(page_paths)} pages... (this can take a long time)')

    tmp_pdf = book_base_path / 'book-tmp.pdf'
    create_pdf(page_paths, tmp_pdf)

    print('Adding the metadata and the table of contents...')
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
            raise f'image at path [{path}] is empty'
        # test-read a byte from it so that we can abort early in case
        # we cannot read data from the file
        with open(path, "rb") as im:
            im.read(1)

    output_pdf = open(output_pdf_path, "wb")
    a4inpt = (img2pdf.mm_to_pt(210),img2pdf.mm_to_pt(297))
    layout_fun = img2pdf.get_layout_fun(a4inpt)
    img2pdf.convert(*image_paths, layout_fun=layout_fun, outputstream=output_pdf)


def generate_output_pdf_filename(base_path):
    try:
        with open(f'{base_path}/manifest.json') as f_manifest:
            manifest = json.load(f_manifest)
    except FileNotFoundError:
        logging.error(f"Couldn't find [{f'{base_path}/manifest.json'}]! Aborting...")
        raise

    title, authors, pub_date, num_pages, publisher = itemgetter('title', 'authors', 'pub_date', 'num_pages',
                                                                'publisher')(manifest['metadata'])
    title = html.unescape(title)
    year = pub_date.split(".")[0]
    authors = html.unescape(authors)

    filename = f'{title} ({year}) — {authors}'
    return to_valid_filename(filename) + '.pdf'


def add_metadata(base_path, pdf):
    try:
        with open(f'{base_path}/manifest.json') as f_manifest:
            manifest = json.load(f_manifest)
    except FileNotFoundError:
        logging.error(f"Couldn't find [{f'{base_path}/manifest.json'}]! Aborting...")
        raise

    language = manifest['language']
    title, authors, pub_date, num_pages, publisher = itemgetter('title', 'authors', 'pub_date', 'num_pages',
                                                                'publisher')(manifest['metadata'])
    pub_date_parts = pub_date.split('.')
    year = int(pub_date_parts[0])
    month = int(pub_date_parts[1]) if len(pub_date_parts) > 1 else 1
    day = int(pub_date_parts[2]) if len(pub_date_parts) > 2 else 1
    title = html.unescape(title)
    authors = html.unescape(authors)
    publisher = html.unescape(publisher)

    with pdf.open_metadata() as pdf_metadata:
        pdf_metadata['dc:title'] = title
        pdf_metadata['dc:creator'] = [author.strip() for author in authors.split(',')]
        pdf_metadata['dc:language'] = [language]
        pdf_metadata['dc:publisher'] = [publisher]
        pdf_metadata['xmp:CreateDate'] = datetime.datetime(year, month, day).isoformat()


def add_toc(book_base_path, pdf):
    try:
        with open(book_base_path / 'toc.json') as f_toc:
            toc = json.load(f_toc)
    except FileNotFoundError:
        logging.error("Couldn't find toc.json! Falling back to manifest.json. The outline structure will be flat...")
        try:
            with open(book_base_path / 'manifest.json') as f_toc:
                toc = json.load(f_toc)['toc_entry']
        except FileNotFoundError:
            logging.error("Couldn't find manifest.json either! Aborting...")
            raise

    if toc is None or len(toc) == 0:
        raise 'No table of contents or no entries'

    with pdf.open_outline() as pdf_outline:
        pdf_outline.root.clear()

        for toc_item in toc:
            label, depth, page_index = itemgetter('label', 'depth', 'page_index')(toc_item)
            label = html.unescape(label)

            parent = pdf_outline.root
            for _ in range(depth):
                parent = parent[-1].children

            outline_item = OutlineItem(html.unescape(label), page_index)
            parent.append(outline_item)


def to_valid_filename(value):
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"[^\w\s\-.,—()]", "", value).strip("-_")
    return value
