#!/usr/bin/env zx

$.verbose = false;

const BOOK_ID = 'BwCMEAAAQBAJ'; // Found in the URL of the book page. For example: BwCMEAAAQBAJ
const GOOGLE_PAGE_DOWNLOAD_PACER = 2 * 1000; // Wait between requests to reduce risk of getting flagged for abuse.


// How to get this options object:
// 1) Go to https://play.google.com/books and login.
// 2) Open dev console, network tab.
// 3) Click somewhere in the page.
// 4) Right-click on the corresponding request in the dev console and then “Copy as Node.js fetch”.
// 5) Options object is the second argument in the call to fetch().
const FETCH_OPTIONS = {};

info(`Script started`);

const book_dir = `books/${BOOK_ID}`;

await $ `mkdir -p ${book_dir}`;
await cd(book_dir);

const body = await fetch(`https://play.google.com/books/reader?id=${BOOK_ID}`, FETCH_OPTIONS).then(t => t.text());

const aes_key = extract_decryption_key(body);
await fs.writeFile('aes_key.bin', aes_key);
success(`Found AES decryption key: [${aes_key}]`);

let toc = extract_toc(body);

const manifest_text = await fetch(`https://play.google.com/books/volumes/${BOOK_ID}/manifest`, FETCH_OPTIONS).then(t => t.text());
const manifest = JSON.parse(manifest_text);
await fs.writeFile('manifest.json', JSON.stringify(manifest, null, 4));

if (!toc) {
    toc = manifest.toc_entry;
    if (toc) {
        warn("Using the table of contents from the manifest as a fallback. Note that it's inferior because everything is flattened to the top level instead of having subchapters");
    } else {
        err("Error! Couldn't find the table of contents in the book manifest");
    }
}

if (toc) {
    await fs.writeFile('toc.json', JSON.stringify(toc, null, 4));
    success("Extracted the table of contents to toc.json");

    try {
        const human_toc = toc.map(t => {
            const indent = '    '.repeat(t.depth);
            const label = `${indent}${unescape_html(t.label)} ........`.padEnd(80, '.');
            return `${label} p.${t.page_index+1}`;
        }).join('\n');
        await fs.writeFile('toc.txt', human_toc);
        success("Wrote human-readable table of contents to toc.txt");
    } catch (e) {
        warn(`Warning: Couldn't produce a human-readable table of contents:\n${e.message}\n${e.stack}`);
    }

}

const missing_pages = manifest.page.filter(p => !p.src || typeof p.src !== 'string').map(p => p.pid);
const missing = missing_pages.length;
const total = manifest.page.length;

if (missing !== 0) {
    const missing_percent = (missing/total).toLocaleString('en-US', {style: 'percent'});
    err(`Error! Couldn't find a download link for ${missing} pages (${missing_percent} missing, total: ${total} pages). Make sure that the FETCH_OPTIONS object is valid and that you own the book. List of missing pages: [${missing_pages.join(',')}]`);
}

const page_files = [];

log(`Starting to download ${total} pages…`);

for (let [i, page] of manifest.page.entries()) {
    const p = `${i+1}/${total}`;

    const { pid, src } = page;
    if (!src) {
        err(`[${p}] Skipped: download link for ${pid} is missing…`);
        continue;
    }

    try {
        const {mimeType, buffer: buf_enc} = await download_page(src);
        const buf = await decrypt(buf_enc);

        const ext = mime_to_ext(mimeType);
        const filename = `${pid}.${ext}`;
        await fs.writeFile(filename, buf);

        page_files.push(filename);

        log(`[${p}] Saved to ${filename} (url: ${src})`);
    } catch (e) {
        err(`[${p}] Error! Download or decrypt failed (url: ${src}) failed with ${e.message}\n${e.stack}`);
    }

    await sleep(GOOGLE_PAGE_DOWNLOAD_PACER); // Be gentle with Google Play Books
}

fs.writeFile('pages.txt', page_files.join('\n'));


info(`Finished. The pages that got successfully downloaded can be found in "${book_dir}".`);


// ================================================
// ============== End of script body ==============
// ================================================

function log(message) {
    return console.log(`[${BOOK_ID}] ${message}`);
}

function info(message) {
    return console.info(chalk.blue(`[${BOOK_ID}] ${message}`));
}

function success(message) {
    return console.info(chalk.green(`[${BOOK_ID}] ${message}`));
}

function warn(message) {
    return console.warn(chalk.yellow(`[${BOOK_ID}] ${message}`));
}

function err(message) {
    return console.error(chalk.red(`[${BOOK_ID}] ${message}`));
}


async function download_page(src) {
    const page_url = new URL(src);
    page_url.searchParams.set('w', 10000); // Arbitrarily high number to make sure that we retrieve the highest resolution
    page_url.searchParams.set('h', 10000);
    page_url.searchParams.delete('edge'); // e.g. `edge=stretch`. This distorts the aspect ratio of the picture, but we want the original.
    page_url.searchParams.set('zoom', 3); // Zoom values 1 and 2 are for thumbnails (degraded quality)
    page_url.searchParams.set('enc_all', 1); // Setting this to 0 returns a non-encrypted image, but it's mangled instead
    page_url.searchParams.set('img', 1);

    const response = await fetch(page_url, FETCH_OPTIONS);

    const mimeType = response.headers.get('content-type');
    const buffer = Buffer.from(await response.arrayBuffer());

    return {mimeType, buffer};
}

async function decrypt(buf) {
    const bytearray = new Uint8Array(buf);
    const iv = bytearray.subarray(0, 16);
    const data = bytearray.subarray(16);

    const key = await crypto.subtle.importKey("raw", aes_key, {
        name: "AES-CBC"
    }, true, ["decrypt", "encrypt"]);

    const decrypted_page_data = await crypto.subtle.decrypt({
        name: "AES-CBC",
        iv: iv
    }, key, data);

    return Buffer.from(decrypted_page_data);
}

function extract_decryption_key(google_reader_body) {
    // There is a fake GIF image in the body of the book reader from which the key is derived
    // const src =
    //     "data:image/gif;base64,[long base64 string]";

    let key_data;
    try {
        // Using a RegExp to avoid adding a DOM parser dependency. It's not pretty because I made it reasonably robust.
        key_data = google_reader_body.match(/<body[^]*?<[^>]+src\s*=\s*["']data:.*?base64,([^"']+)["']/)[1];
    } catch (e) {
        throw new Error(`Failed to extract the encoded decryption key from Play Book Reader's HTML body: ${google_reader_body}`, {cause: e});
    }

    return decipher_key(atob(key_data));
}

function extract_toc(google_reader_body) {
    let toc_data;
    try {
        // Extract the table of contents from the embedded json object of the script in Play Book Reader's page.
        // The ToC from this page properly supports nested ToCs, whereas the book manifest only contains a flattened ToC.
        toc_data = google_reader_body.match(/"toc_entry":\s*(\[[^]*?\}\s*\])/)[1];
    } catch (e) {
        warn(`Failed to extract the table of contents from the book's main page. Error: ${e.message}, stack:\n${e.stack}`);
        return null;
    }

    try {
        return JSON.parse(toc_data);
    } catch (e) {
        warn(`Failed to parse the table of contents from the book's main page as JSON. Content: ${toc_data}\n Error: ${e.message}, stack:\n${e.stack}`);
        return null;
    }
}



function decipher_key(str) {
    const groups = str.match(/(\D+\d)/g);
    if (groups.length !== 128) {
        warn(`Unexpected count of AES key groups. Expected: 128, got: ${groups.length}. Ignoring the error and continuing…`);
    }

    let bitfield = groups.map((s) => {
        const pos = Number(s.at(-1));
        if (s.at(pos) === s.at(-2)) {
            return '1';
        } else {
            return '0';
        }
    });

    const pivot = 64;
    const shift = pivot % bitfield.length;

    if (shift > 0) {
        Array.prototype.unshift.apply(bitfield, bitfield.splice(-shift, shift));
    } else if (shift < 0) {
        Array.prototype.push.apply(bitfield, bitfield.splice(0, -shift));
    }

    const key  = [];
    for (let pos = 0; pos < bitfield.length; pos += 8) {
        const bin = bitfield.slice(pos, pos + 8).reverse().join('');
        key.push(parseInt(bin, 2));
    }

    return new Uint8Array(key);
}

function mime_to_ext(mime) {
    const lookup = {
        'image/png': 'png',
        'image/jpeg': 'jpeg',
        'image/webp': 'webp',
        'image/apng': 'apng',
        'image/jp2': 'jp2',
        'image/jpx': 'jpx',
        'image/jpm': 'jpm',
        'image/bmp': 'bmp',
        'image/svg+xml': 'svg',
    };

    if (mime in lookup) {
        return lookup[mime];
    }

    warn(`Unknown image mime: ${mime}`);
    return 'unk';
}

function unescape_html(str) {
  return str.replace(/&#(\d+);/g, (match, code) => {
    return String.fromCharCode(code);
  });
}
