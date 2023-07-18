#!/usr/bin/env zx

import * as aes from "aes-cross";

$.verbose = false;

const FETCH_OPTIONS = {};

const BOOK_ID = 'BwCMEAAAQBAJ'; // Found in the URL of the book page. For example: BwCMEAAAQBAJ
const GOOGLE_PAGE_DOWNLOAD_PACER = 100; // Wait between requests to reduce risk of getting flagged for abuse. The official frontend sequentially spams the segments API without wait so it should be safe to put a crazy number here.

const aes_key_raw = await fs.readFile(`books/${BOOK_ID}/aes_key.bin`);
const aes_key = new Uint8Array(aes_key_raw);
console.log(`[aes_key]: ${aes_key}\n`);
console.log(aes_key);

const manifest = JSON.parse(await fs.readFile(`books/${BOOK_ID}/manifest.json`));

const total = manifest.segment.length;
const segment_files = [];

log(`Starting to download ${total} segments…`);

for (const segment of manifest.segment) {
  // const p = `${i + 1}/${total}`;

  const segment_url = 'https://play.google.com' + segment.link;
  try {
    console.log(`===> segment #${segment.order}: ${segment.label} (${segment.title})`);

    const response = await fetch_segment(segment_url)
    const buf_text = await response.text();
    console.log(buf_text.length);

    const buf_tmp = Buffer.from(buf_text, 'base64');
    console.log(buf_tmp);

    const buf = await decrypt(new Uint8Array(buf_tmp));

    const filename = `${segment.order} - ${segment.title}.json`;
    await fs.writeFile(filename, JSON.stringify(buf, null, 4));

    segment_files.push(filename);

    log(`Saved to ${filename} (url: ${segment_url})`);
  } catch (e) {
    err(`Error! Download or decrypt failed (url: ${segment_url}) failed with ${e.message}\n${e.stack}`);
  }

  await sleep(GOOGLE_PAGE_DOWNLOAD_PACER); // Be gentle with Google Play Books
}

// const buf_enc = new Uint8Array(Buffer.from(b64_str, 'base64'));
//
// const buf = await decrypt(buf_enc);


async function decrypt(buf) {
  const bytearray = new Uint8Array(buf);
  // console.log(`\n[buf]:`);
  // console.log(bytearray);

  const iv = bytearray.subarray(0, 16);
  console.log(`\n[iv]:`);
  console.log(iv);

  const str_expected_length_bin = bytearray.subarray(16, 20);

  // Has custom padding, includes the real string length so that we can cut the output to remove the padding.
  const str_expected_length = Buffer.from(str_expected_length_bin).readUInt32LE();
  console.log(`\n[str_expected_length]: ${str_expected_length}`);

  const data = bytearray.subarray(20);
  console.log(`[str_buf_size]: ${data.length}`);
  // console.log(data);

  try {
    const dec = aes.dec(data, aes_key, iv, 'binary', 'binary', 'aes-128-cbc', false);
    const dec_payload = Buffer.from(dec).toString('utf-8');
    const dec_payload_cut = dec_payload.substring(0, str_expected_length);
    // console.log(dec_payload);

    try {
      console.log(dec_payload_cut);
      const dec_payload_json = JSON.parse(dec_payload_cut);
      return dec_payload_json;
    } catch (e) {
      console.log(e);
      return dec_payload_cut;
    }
  } catch (e) {
    console.log(e);
  }
}

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

async function fetch_segment(src) {
  const segment_url = new URL(src);
  segment_url.searchParams.set('enc_all', 1); // If we set it to 0 only the book content fields are encrypted in the JSON. Setting this to 1 encrypts the whole JSON which is easier because we can decrypt it in one go without wondering every time if a given field is encrypted or not.

  console.log(`fetch: ${segment_url}`);
  return fetch(segment_url, FETCH_OPTIONS);
}
