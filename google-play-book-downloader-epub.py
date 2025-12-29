#!/usr/bin/env python3

import os
import time
import json
import base64
import requests
import logging
import re
from urllib.parse import urlparse, urlencode, urlunparse, parse_qs
from Cryptodome.Cipher import AES
from bs4 import BeautifulSoup

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format="[%(asctime)s] %(levelname)s: %(message)s")

BOOK_ID = "BwCMEAAAQBAJ"  # Found in the URL of the book page. For example: BwCMEAAAQBAJ
GOOGLE_PAGE_DOWNLOAD_PACER = 0.1  # Wait between requests to reduce risk of getting flagged for abuse

# How to get this options object:
# 1) Go to https://play.google.com/books and log in.
# 2) Open dev console, network tab.
# 3) Click somewhere in the page.
# 4) Right-click on the corresponding request in the dev console and then “Copy as cURL”.
# 5) Go to https://curlconverter.com/python/ and paste your clipboard in the input box.
# 6) From the Python code that was generated just copy the cookies and the headers to replace the two lines below:
cookies = {}
headers = {}


def log(message):
    logging.info(f"[{BOOK_ID}] {message}")


def info(message):
    logging.info(f"[{BOOK_ID}] {message}")


def success(message):
    logging.info(f"[{BOOK_ID}] {message}")


def warn(message):
    logging.warning(f"[{BOOK_ID}] {message}")


def err(message):
    logging.error(f"[{BOOK_ID}] {message}")


def decode_html_entities(text):
    return re.sub(r"&#(\d+);", lambda match: chr(int(match.group(1))), text)


def download_resource_to_base64(url):
    response = requests.get(url, headers=headers, cookies=cookies)
    buffer = response.content
    content_type = response.headers.get("content-type", "application/octet-stream")
    data = base64.b64encode(buffer).decode("utf-8")
    return {"contentType": content_type, "data": data}


def embed_resource(element, data_url):
    tag_name = element.name.lower()
    if tag_name == "style":
        element.string = f"@import url({data_url});"
    elif tag_name == "img":
        element["src"] = data_url
        element.attrs.pop("width", None)
        element.attrs.pop("height", None)
    else:
        element["src"] = data_url


def embed_resources_as_base64(html_string):
    soup = BeautifulSoup(html_string, "html.parser")
    resource_elements = soup.select(
        'img[src^="http"], link[rel="stylesheet"][href^="http"], script[src^="http"], audio[src^="http"], video[src^="http"], source[src^="http"], object[data^="http"], embed[src^="http"], iframe[src^="http"], *[style*="url(http"]'
    )

    for element in resource_elements:
        url = element.get("src") or element.get("href") or element.get("data")
        resource = download_resource_to_base64(url)
        data_url = f"data:{resource['contentType']};base64,{resource['data']}"
        embed_resource(element, data_url)

    return str(soup)


def decrypt(buf, aes_key):
    iv = buf[:16]
    str_expected_length = int.from_bytes(buf[16:20], "little")
    data = buf[20:]

    cipher = AES.new(aes_key, AES.MODE_CBC, iv)
    decrypted_page_data = cipher.decrypt(data)

    return decrypted_page_data[:str_expected_length].decode("utf-8")


def fetch_segment(url):
    segment_url = urlparse(url)
    query = parse_qs(segment_url.query)
    query["enc_all"] = ["1"]
    # Fix encoding issues with Cyrillic
    query["hl"] = ["en"]
    segment_url = segment_url._replace(query=urlencode(query, doseq=True))
    full_url = urlunparse(segment_url)

    response = requests.get(full_url, headers=headers, cookies=cookies)
    return response


book_dir = f"books/{BOOK_ID}"
os.makedirs(book_dir, exist_ok=True)
os.chdir(book_dir)
os.makedirs("segments", exist_ok=True)

with open("aes_key.bin", "rb") as f:
    aes_key = f.read()

with open("manifest.json", "r") as f:
    manifest = json.load(f)

total = len(manifest["segment"])
segment_files = []

with open("segments.txt", "w") as segments_file:
    segments_file.writelines(
        list(map(lambda s: s["label"] + "\n", manifest["segment"])))

log(f"Starting to download {total} segments…")

for segment in manifest["segment"]:
    segment_url = "https://play.google.com" + segment["link"]
    try:
        log(f"===> segment #{segment['order']}: {segment['label']} ({segment['title']})")
        response_enc_b64 = fetch_segment(segment_url).text
        response_enc = base64.b64decode(response_enc_b64)
        response = decrypt(response_enc, aes_key)

        label = segment["label"]

        with open(f"segments/{label}.json", "w", encoding="utf-8") as f:
            json.dump(response, f, indent=4)

        segment_obj = json.loads(response)

        html = segment_obj["content"]
        css = segment_obj["style"]

        # FIXME: what if label is not actually unique?
        with open(f"{label}.xhtml", "w", encoding="utf-8") as f:
            f.write(html)
        with open(f"{label}.css", "w", encoding="utf-8") as f:
            f.write(css)

        # Old stuff

        filename = decode_html_entities(f"{segment['order']} - {segment['title']}.json")
        with open(f"segments/{filename}", "w", encoding="utf-8") as f:
            json.dump(segment, f, indent=4)

        fixed_html = embed_resources_as_base64(html)
        with open(f"segments/{filename}.css", "w", encoding="utf-8") as f:
            f.write(css)
        with open(f"segments/{filename}.html", "w", encoding="utf-8") as f:
            f.write(f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta http-equiv="Content-Type" content="text/html; charset=utf-8">
  <link rel="stylesheet" href="{filename}.css">
</head>
<body>
  {fixed_html}
</body>
</html>""")

        segment_files.append(filename)
        log(f"Saved to {filename} (url: {segment_url})")
    except Exception as e:
        err(f"Error! Download or decrypt failed (url: {segment_url}) failed with {e}")

    time.sleep(GOOGLE_PAGE_DOWNLOAD_PACER)

info(
    f'Finished. The segments that got successfully downloaded can be found in "{book_dir}/segments".')
