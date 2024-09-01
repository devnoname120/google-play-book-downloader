#!/usr/bin/env python3

import json
import logging
import pathlib

from ebooklib import epub
from ebooklib.epub import EpubBook, EpubHtml, EpubItem, EpubNcx, EpubNav
from pydash import _, unescape, trim, curry, replace

BOOK_ID = "BwCMEAAAQBAJ"


base_path = pathlib.Path(f"books/{BOOK_ID}")
try:
    with open(f"{base_path}/manifest.json") as f_xhtml:
        manifest = json.load(f_xhtml)
except FileNotFoundError:
    logging.error(f"Couldn't find [{f'{base_path}/manifest.json'}]! Aborting...")
    raise

metadata = manifest["metadata"]
volume_id = metadata["volume_id"]

# TODO: get the ISBN and LCCN by parsing https://books.google.com/books/download?id=Udv-AwAAQBAJ&output=bibtex
# Note that the ISBN and LCCN are not always available, for example BwCMEAAAQBAJ doesn't have either
# 2014027001 = lccn number from the bibtex (Library of Congress Control Number)
# https://lccn.loc.gov/2014027001/marcxml
# or https://lccn.loc.gov/2014027001/mods (looks best)
# or https://lccn.loc.gov/2014027001/dc (output is a bit weird)
# See this for converting marcxml to Dublin Core https://gist.github.com/jermnelson/b1d908044f02032d2953
# https://loc.gov/item/2014027001 (embedded JSON in HMTL source is very nice. Search for created_published to find it)

book = EpubBook()

# FIXME: use a proper urn:uuid identifier (see real-epub-export-from-google.opf)
book.set_identifier(volume_id)
book.set_title(metadata["title"])

_(metadata["authors"]).split(',').map(curry(trim, 1)).map(unescape).for_each(
    curry(book.add_author, 1)).value()

book.add_metadata('DC', 'publisher', metadata["publisher"])
book.add_metadata('DC', 'date', replace(metadata["pub_date"], ".", "-"))
book.add_metadata('DC', 'source',
                  f"https://books.google.com/books?id={volume_id}")
book.add_metadata('DC', 'source',
                  f"https://play.google.com/store/books/details?id={volume_id}")

book.set_language(manifest["language"])

if manifest.get("is_right_to_left"):
    book.set_direction("rtl")

# FIXME: we can't assume that the cover will always be PP1.jpeg.
#        iirc the cover url is available somewhere and can be easily downloaded
with open(f"{base_path}/PP1.jpeg", 'rb') as f:
    book.set_cover("cover.jpg", f.read())

chapters = []

for segment in manifest["segment"]:
    title = segment["title"]
    label = segment["label"]

    xhtml_filename = f"{label}.xhtml"
    css_filename = f"{label}.css"

    try:
        with open(f"{base_path}/{xhtml_filename}", "r") as f:
            xhtml = f.read()
        with open(f"{base_path}/{css_filename}", "r") as f:
            css = f.read()
    except FileNotFoundError:
        logging.error(
            f"Couldn't find [{base_path}/{xhtml_filename} or {base_path}/{css_filename}]! Aborting...")
        raise

    chapter = EpubHtml(title=title, file_name=xhtml_filename, content=xhtml)

    css_item = EpubItem(file_name=css_filename, media_type="text/css",
                        content=css)
    # book.add_item() adds the css file in the EPUB
    # chapter.add_item() only adds a link to the css file stored in the EPUB but it doesn't add the css file itself.
    # Yes, it's super confusing that the latter doesn't do both...
    book.add_item(css_item)
    chapter.add_item(css_item)

    book.add_item(chapter)

    chapters.append(chapter)

book.toc = chapters

# EPUB toc/navigation metadata stuff
book.add_item(EpubNcx())
book.add_item(EpubNav())

style = "BODY {color: white;}"
nav_css = EpubItem(
    uid="style_nav",
    file_name="style/nav.css",
    media_type="text/css",
    content=style,
)

book.add_item(nav_css)

book.spine = ["cover", "nav", *chapters]

epub.write_epub(f"{base_path}/book.epub", book, {})
