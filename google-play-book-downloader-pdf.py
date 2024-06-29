#!/usr/bin/env python3

import os
import time
import json
import re
import requests
import base64
import logging

from urllib.parse import urlparse, urlencode, urlunparse, parse_qs
from Cryptodome.Cipher import AES

BOOK_ID = ''  # Found in the URL of the book page. For example: BwCMEAAAQBAJ
GOOGLE_PAGE_DOWNLOAD_PACER = 0.5  # Wait between requests to reduce risk of getting flagged for abuse.

# How to get this options object:
# 1) Go to https://play.google.com/books and log in.
# 2) Open dev console, network tab.
# 3) Click somewhere in the page.
# 4) Right-click on the corresponding request in the dev console and then “Copy as cURL”.
# 5) Go to https://curlconverter.com/python/ and paste your clipboard in the input box.
# 6) From the Python code that was generated just copy the cookies and the headers to replace the two lines below:
cookies = {}
headers = {}

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='[%(asctime)s] %(levelname)s: %(message)s')

logging.info(f'Script started for book id: {BOOK_ID}')

book_dir = f'books/{BOOK_ID}'
os.makedirs(book_dir, exist_ok=True)
os.chdir(book_dir)

response = requests.get(f'https://play.google.com/books/reader?id={BOOK_ID}&hl=en',
                        cookies=cookies,
                        headers=headers)
body = response.text


def unescape_html(text):
    return re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), text)


def extract_decryption_key(google_reader_body):
    try:
        key_search = re.search(
            r'<body[\s\S]*?<[^>]+src\s*=\s*["\']data:.*?base64,([^"\']+)["\']',
            google_reader_body)

        key_data = key_search.group(1)

        logging.info(f'Ciphered decryption key: {base64.b64decode(key_data)}')
    except Exception as e:
        raise Exception(
            f'Failed to extract the encoded decryption key from Play Book Reader\'s HTML body: {google_reader_body}') from e

    return decipher_key(base64.b64decode(key_data, validate=True))


def decipher_key(str_data):
    groups = re.findall(r'(\D+\d)', str_data.decode())
    if len(groups) != 128:
        logging.warning(
            f'Unexpected count of AES key groups. Expected: 128, got: {len(groups)}. Ignoring the error and continuing…')

    bitfield = [str(1 if s[int(s[-1])] == s[-2] else 0) for s in groups]
    shift = 64 % len(bitfield)

    if shift > 0:
        bitfield = bitfield[-shift:] + bitfield[:-shift]
    elif shift < 0:
        bitfield = bitfield[-shift:] + bitfield[0:-shift]

    key = []
    for pos in range(0, len(bitfield), 8):
        bin_str = ''.join(reversed(bitfield[pos:pos + 8]))
        key.append(int(bin_str, 2))
    return bytes(key)


aes_key = extract_decryption_key(body)
with open('aes_key.bin', 'wb') as key_file:
    key_file.write(aes_key)
logging.info(f'Found AES decryption key: [{aes_key.hex()}]')


def extract_toc(google_reader_body):
    try:
        toc_data = re.search(r'"toc_entry":\s*(\[[\s\S]*?}\s*])',
                             google_reader_body).group(1)
    except Exception as e:
        logging.warning(
            f'Failed to extract the table of contents from the book\'s main page. Error: {e}')
        return None

    try:
        return json.loads(toc_data)
    except Exception as e:
        logging.warning(
            f'Failed to parse the table of contents from the book\'s main page as JSON. Content: {toc_data} Error: {e}')
        return None


toc = extract_toc(body)

manifest_response = requests.get(
    f'https://play.google.com/books/volumes/{BOOK_ID}/manifest?hl=en&authuser=2&source=ge-web-app',
    cookies=cookies, headers=headers)
manifest_text = manifest_response.text
manifest = json.loads(manifest_text)
with open('manifest.json', 'w') as manifest_file:
    json.dump(manifest, manifest_file, indent=4)

if not toc:
    toc = manifest.get('toc_entry')
    if toc:
        logging.warning(
            "Using the table of contents from the manifest as a fallback. Note that it's inferior because everything is flattened to the top level instead of having subchapters")
    else:
        logging.error("Error! Couldn't find the table of contents in the book manifest")

if toc:
    with open('toc.json', 'w') as toc_file:
        json.dump(toc, toc_file, indent=4)
    logging.info("Extracted the table of contents to toc.json")

    try:
        human_toc = '\n'.join(
            f"{'    ' * t['depth']}{unescape_html(t['label'])} ........".ljust(80,
                                                                               '.') + f" p.{t['page_index'] + 1}"
            for t in toc
        )
        with open('toc.txt', 'w') as human_toc_file:
            human_toc_file.write(human_toc)
        logging.info("Wrote human-readable table of contents to toc.txt")
    except Exception as e:
        logging.warning(
            f"Warning: Couldn't produce a human-readable table of contents:\n{e}")

missing_pages = [p['pid'] for p in manifest['page'] if
                 not p.get('src') or not isinstance(p['src'], str)]
missing = len(missing_pages)
total = len(manifest['page'])

if missing != 0:
    missing_percent = f"{(missing / total):.2%}"
    logging.error(
        f"Error! Couldn't find a download link for {missing} pages ({missing_percent} missing, total: {total} pages). Make sure that the FETCH_OPTIONS object is valid and that you own the book. List of missing pages: [{', '.join(map(str, missing_pages))}]")

page_files = []

logging.info(f"Starting to download {total} pages…")


def download_page(src):
    url_parts = list(urlparse(src))
    query = parse_qs(url_parts[4])
    query.update({
        'w': ['10000'],
        # Arbitrarily high number to make sure that we retrieve the highest resolution
        'h': ['10000'],
        'zoom': ['3'],  # Zoom values 1 and 2 are for thumbnails (degraded quality)
        'enc_all': ['1'],
        'img': ['1']
    })
    url_parts[4] = urlencode(query, doseq=True)
    page_url = urlunparse(url_parts)
    logging.info(f"Downloading url: {page_url}")

    response = requests.get(page_url, cookies=cookies, headers=headers)

    mimeType = response.headers.get('content-type')
    buffer = response.content

    return mimeType, buffer


def decrypt(buf):
    iv = buf[:16]
    data = buf[16:]

    key = AES.new(aes_key, AES.MODE_CBC, iv)
    decrypted_page_data = key.decrypt(data)

    return decrypted_page_data


def mime_to_ext(mime):
    lookup = {
        'image/png': 'png',
        'image/jpeg': 'jpeg',
        'image/webp': 'webp',
        'image/apng': 'apng',
        'image/jp2': 'jp2',
        'image/jpx': 'jpx',
        'image/jpm': 'jpm',
        'image/bmp': 'bmp',
        'image/svg+xml': 'svg',
    }

    return lookup.get(mime, 'unk')


for i, page in enumerate(manifest['page']):
    p = f"{i + 1}/{total}"

    pid, src = page.get('pid'), page.get('src')
    if not src:
        logging.error(f"[{p}] Skipped: download link for {pid} is missing…")
        continue

    try:
        mimeType, buf_enc = download_page(src)
        buf = decrypt(buf_enc)

        ext = mime_to_ext(mimeType)
        filename = f"{pid}.{ext}"
        with open(filename, 'wb') as file:
            file.write(buf)

        page_files.append(filename)

        logging.info(f"[{p}] Saved to {filename}")
    except Exception as e:
        logging.error(f"[{p}] Error! Download or decrypt failed with {e}")

    time.sleep(GOOGLE_PAGE_DOWNLOAD_PACER)  # Be gentle with Google Play Books

with open('pages.txt', 'w') as pages_file:
    pages_file.write('\n'.join(page_files))

logging.info(
    f'Finished. The pages that got successfully downloaded can be found in "{book_dir}".')
