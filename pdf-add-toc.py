import datetime
import json
from pikepdf import Pdf, OutlineItem
from operator import itemgetter
import logging


def main():
    pdf = Pdf.open('combined-no-toc.pdf')
    add_metadata(pdf)
    add_toc(pdf)
    pdf.save('combined-with-metadata.pdf', linearize=True)


def add_metadata(pdf):
    try:
        f_manifest = open('manifest.json')
        manifest = json.load(f_manifest)
    except FileNotFoundError:
        logging.error("Couldn't find manifest.json! Aborting...")
        raise

    language = manifest['language']
    title, authors, pub_date, num_pages, publisher = itemgetter('title', 'authors', 'pub_date', 'num_pages',
                                                                'publisher')(manifest['metadata'])

    year, month, day = [int(x) for x in pub_date.split('.')]

    with pdf.open_metadata() as pdf_metadata:
        pdf_metadata['dc:title'] = title
        pdf_metadata['dc:creator'] = [author.strip() for author in authors.split(',')]
        pdf_metadata['dc:language'] = [language]
        pdf_metadata['dc:publisher'] = [publisher]
        pdf_metadata['xmp:CreateDate'] = datetime.datetime(year, month, day).isoformat()


def add_toc(pdf):
    try:
        f_toc = open('toc.json')
        toc = json.load(f_toc)
    except FileNotFoundError:
        logging.error("Couldn't find toc.json! Falling back to manifest.json. The outline structure will be flat...")
        try:
            f_toc = open('manifest.json')
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

            parent = pdf_outline.root
            for i in range(depth):
                parent = parent[-1].children

            outline_item = OutlineItem(label, page_index)
            parent.append(outline_item)


if __name__ == '__main__':
    main()
