#!/usr/bin/env python3

import os
import time
import json
import re
import requests
import base64
import logging
import argparse

from urllib.parse import urlparse, urlencode, urlunparse, parse_qs
from Cryptodome.Cipher import AES

GOOGLE_PAGE_DOWNLOAD_PACER = 0.1  # Wait between requests to reduce risk of getting flagged for abuse.


def main():
    BOOK_ID = input("Type your book ID and press enter: ")

    logging.basicConfig(level=logging.INFO,
                        format="[%(asctime)s] %(levelname)s: %(message)s")

    try:
        with open("curl.txt", "r") as f:
            curl_command = f.read().strip()
    except FileNotFoundError:
        print("""\nYou will need to provide your cookies in order to download books. Here is how:
1) Go to https://play.google.com/books and log in.
2) Open dev console, network tab.
3) Click on the book you want to read (the link should have the format https://play.google.com/books/reader?id=xxxxxxxxxx)
4) In the network tab of the dev console type "segment" (without the quotes) in the filter box.
5) Right-click on the first request (it should appear as segment?authuser=0&xxxxxxxxx) in the dev console and then click on "Copy as cURL", or "Copy as cURL (bash)", or "Copy as cURL (POSIX)" whichever appears (the name of this option depends on your browser and OS).
6) Create the file curl.txt and paste it inside\n""")
        raise FileNotFoundError("curl.txt file not found. Please create it and put the curl command from the browser.")
    except IOError as e:
        raise IOError(f"Error reading curl.txt: {e}")

    try:
        url, cookies, headers = parse_curl_command(curl_command)
    except ValueError as e:
        raise ValueError(f"Failed to parse curl command: {e}")

    if url.netloc != "play.google.com":
        raise ValueError(f"Invalid curl command in curl.txt. The domain name should be to 'play.google.com' but in the command it is: {url.netloc}")


    logging.info(f"Script started for book id: {BOOK_ID}")

    book_dir = f"books/{BOOK_ID}"
    os.makedirs(book_dir, exist_ok=True)
    os.chdir(book_dir)

    # &hl=en is necessary to fix encoding issues with Cyrillic
    response = requests.get(f"https://play.google.com/books/reader?id={BOOK_ID}&hl=en",
                            cookies=cookies, headers=headers)
    body = response.text

    aes_key = extract_decryption_key(body)
    with open("aes_key.bin", "wb") as key_file:
        key_file.write(aes_key)
    logging.info(f"Found AES decryption key: [{aes_key.hex()}]")

    toc = extract_toc(body)

    manifest_response = requests.get(
        f"https://play.google.com/books/volumes/{BOOK_ID}/manifest?hl=en&authuser=2&source=ge-web-app",
        cookies=cookies,
        headers=headers,
    )
    manifest_text = manifest_response.text
    manifest = json.loads(manifest_text)
    with open("manifest.json", "w") as manifest_file:
        json.dump(manifest, manifest_file, indent=4)

    if manifest.get("metadata", {}).get("preview") != "full":
        logging.error(f"The server indicates that the book is in preview mode '{manifest.get('preview')}' (expected 'full'). This either means that you don't own the book on this account, or that your curl command is invalid/expired. Delete curl.txt and follow the instructions again!")

    if not toc:
        toc = manifest.get("toc_entry")
        if toc:
            logging.warning(
                "Using the table of contents from the manifest as a fallback. Note that it's inferior because everything is flattened to the top level instead of having subchapters"
            )
        else:
            logging.error("Error! Couldn't find the table of contents in the book manifest")

    if toc:
        with open("toc.json", "w") as toc_file:
            json.dump(toc, toc_file, indent=4)
        logging.info("Extracted the table of contents to toc.json")

        try:
            human_toc = "\n".join(
                f"{'    ' * t['depth']}{unescape_html(t['label'])} ........".ljust(80,
                                                                                   ".") + f" p.{t['page_index'] + 1}"
                for t in toc
            )
            with open("toc.txt", "w") as human_toc_file:
                human_toc_file.write(human_toc)
            logging.info("Wrote human-readable table of contents to toc.txt")
        except Exception as e:
            logging.warning(
                f"Warning: Couldn't produce a human-readable table of contents:\n{e}")

    missing_pages = [p["pid"] for p in manifest["page"] if
                     not p.get("src") or not isinstance(p["src"], str)]
    missing = len(missing_pages)
    total = len(manifest["page"])

    if missing != 0:
        missing_percent = f"{(missing / total):.2%}"
        logging.error(
            f"Error! Couldn't find a download link for {missing} pages ({missing_percent} missing, total: {total} pages).List of missing pages: [{', '.join(map(str, missing_pages))}]"
        )

    page_files = []

    logging.info(f"Starting to download {total} pages…")

    for i, page in enumerate(manifest["page"]):
        p = f"{i + 1}/{total}"

        pid, src = page.get("pid"), page.get("src")
        if not src:
            logging.error(f"[{p}] Skipped: download link for {pid} is missing…")
            continue

        try:
            mimeType, buf_enc = download_page(src, cookies, headers)
            buf = decrypt(buf_enc, aes_key)

            ext = mime_to_ext(mimeType)
            filename = f"{pid}.{ext}"
            with open(filename, "wb") as file:
                file.write(buf)

            page_files.append(filename)

            logging.info(f"[{p}] Saved to {filename}")
        except Exception as e:
            logging.error(f"[{p}] Error! Download or decrypt failed with {e}")

        time.sleep(GOOGLE_PAGE_DOWNLOAD_PACER)  # Be gentle with Google Play Books

    with open("pages.txt", "w") as pages_file:
        pages_file.write("\n".join(page_files))

    logging.info(
        f'Finished. The pages that got successfully downloaded can be found in "{book_dir}".')

def parse_curl_command(curl_command: str):
    # Windows cmd.exe use ^ as an escape character, so browsers put them when copying a request as cURL which breaks our command parsing
    # See: https://github.com/devnoname120/google-play-book-downloader/issues/28#issuecomment-3192839244
    def is_likely_cmd_exe_command(cmd: str):
        return re.search(r'\\^$', cmd, re.MULTILINE) or '^\\^"' in cmd or '^"^' in cmd

    if is_likely_cmd_exe_command(curl_command):
        logging.info(f"The command in curl.txt seems to be for Windows cmd.exe (normal if you copied it from your browser running on Windows)")
        import mslex
        def normalize_windows_cmd_caret(s: str) -> str:
            s = s.replace("\r\n", "\n").strip()
            s = re.sub(r"\s*\^\s*\n\s*", " ", s)
            s = re.sub(r"\^(.)", r"\1", s)
            return s
        try:
            [prog_name, *arg_list] = mslex.split(normalize_windows_cmd_caret(curl_command))
        except ValueError:
            logging.warning(f'Failed to parse curl.txt as a Windows command! Will try again assuming it\'s a command for Linux/macOS shells (NOT normal unless you used the option "Copy as cURL (bash)")')
            import shlex
            [prog_name, *arg_list] = shlex.split(curl_command.strip())
    else:
        logging.info(f'curl.txt seems to be for Linux/macOS shells (normal if copied on these OSs, or from Windows using the option "Copy as cURL (bash)")')
        import shlex
        [prog_name, *arg_list] = shlex.split(curl_command.strip())

    if prog_name != "curl":
        raise ValueError(f"Invalid curl command in curl.txt. The program name should be 'curl' but in the command it is: {prog_name}. Make sure you followed the instructions properly!")

    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--header", "-H", action="append", dest="headers")
    parser.add_argument("--cookie", "-b", action="append", dest="cookies")

    args, _ = parser.parse_known_args(arg_list)

    url = urlparse(args.url)

    headers = {}
    if not args.headers:
        logging.warning(f"No headers detected in curl.txt! You likely didn't properly copy the cURL request to curl.txt")
    else:
        for header in args.headers:
            key, value = header.split(":", 1)
            headers[key.strip()] = value.strip()

    cookies = {}
    if not args.cookies:
        logging.error(f"No cookies detected in curl.txt! You didn't properly copy the cURL request to curl.txt so the book will not be able to download correctly")
    else:
        for cookie in args.cookies:
            cookie_parts = cookie.split(";")
            for cookie in cookie_parts:
                if "=" in cookie:
                    key, value = cookie.split("=", 1)
                    cookies[key.strip()] = value.strip()
                else:
                    logging.warning(f"Invalid cookie (no assigment): {cookie}")

    return url, cookies, headers

def unescape_html(text):
    return re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), text)


def extract_decryption_key(google_reader_body):
    try:
        key_search = re.search(
            r'<body[\s\S]*?<[^>]+src\s*=\s*["\']data:.*?base64,([^"\']+)["\']',
            google_reader_body)

        key_data = key_search.group(1)

        logging.info(f"Ciphered decryption key: {base64.b64decode(key_data)}")
    except Exception as e:
        raise Exception(
            f"Failed to extract the encoded decryption key from Play Book Reader's HTML body: {google_reader_body}"
        ) from e

    return decipher_key(base64.b64decode(key_data, validate=True))


def decipher_key(str_data):
    groups = re.findall(r"(\D+\d)", str_data.decode())
    if len(groups) != 128:
        logging.warning(
            f"Unexpected count of AES key groups. Expected: 128, got: {len(groups)}. Ignoring the error and continuing…"
        )

    bitfield = [str(1 if s[int(s[-1])] == s[-2] else 0) for s in groups]
    shift = 64 % len(bitfield)

    if shift > 0:
        bitfield = bitfield[-shift:] + bitfield[:-shift]
    elif shift < 0:
        bitfield = bitfield[-shift:] + bitfield[0:-shift]

    key = []
    for pos in range(0, len(bitfield), 8):
        bin_str = "".join(reversed(bitfield[pos: pos + 8]))
        key.append(int(bin_str, 2))
    return bytes(key)


def extract_toc(google_reader_body):
    try:
        toc_data = re.search(r'"toc_entry":\s*(\[[\s\S]*?}\s*])',
                             google_reader_body).group(1)
    except Exception as e:
        logging.warning(
            f"Failed to extract the table of contents from the book's main page. Error: {e}")
        return None

    try:
        return json.loads(toc_data)
    except Exception as e:
        logging.warning(
            f"Failed to parse the table of contents from the book's main page as JSON. Content: {toc_data} Error: {e}"
        )
        return None


def download_page(src, cookies, headers):
    url_parts = list(urlparse(src))
    query = parse_qs(url_parts[4])
    query.update(
        {
            "w": ["10000"],
            # Arbitrarily high number to make sure that we retrieve the highest resolution
            "h": ["10000"],
            "zoom": ["3"],  # Zoom values 1 and 2 are for thumbnails (degraded quality)
            "enc_all": ["1"],
            "img": ["1"],
        }
    )
    url_parts[4] = urlencode(query, doseq=True)
    page_url = urlunparse(url_parts)
    logging.info(f"Downloading url: {page_url}")

    response = requests.get(page_url, cookies=cookies, headers=headers)

    mimeType = response.headers.get("content-type")
    buffer = response.content

    return mimeType, buffer


def decrypt(buf, aes_key):
    iv = buf[:16]
    data = buf[16:]

    key = AES.new(aes_key, AES.MODE_CBC, iv)
    decrypted_page_data = key.decrypt(data)

    return decrypted_page_data


def mime_to_ext(mime):
    lookup = {
        "image/png": "png",
        "image/jpeg": "jpeg",
        "image/webp": "webp",
        "image/apng": "apng",
        "image/jp2": "jp2",
        "image/jpx": "jpx",
        "image/jpm": "jpm",
        "image/bmp": "bmp",
        "image/svg+xml": "svg",
    }

    return lookup.get(mime, "unk")


if __name__ == "__main__":
    main()
