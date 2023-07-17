#!/usr/bin/env zx

import * as aes from "aes-cross";

$.verbose = false;

const aes_key_raw = await fs.readFile('books/BwCMEAAAQBAJ/aes_key.bin');
const aes_key = new Uint8Array(aes_key_raw);
console.log(`[aes_key]: ${aes_key}\n`);
console.log(aes_key);

const dir_path = '/Users/paul/Response_Body.folder';

const names = await fs.readdir(dir_path);
// const names = ['[97] Response - play.google.com_books_volumes_BwCMEAAAQBAJ_content_segment'];

for (const name of names) {
  if (!name.includes('content_segment') || name.includes('.dec')) {
    continue;
  }
  console.log(name)
  const name_path = `${dir_path}/${name}`;
  const buf_enc = await fs.readFile(name_path, 'utf8');
  // console.log(buf_enc);
  const buf = await decrypt(new Uint8Array(Buffer.from(buf_enc, 'base64')));
  await fs.writeFile(`${name_path}.dec`, buf);

  try {
    const parsed_buf = JSON.parse(buf);
    await fs.writeFile(`${name_path}.dec.html`, parsed_buf.content);
  } catch (e) {
    console.log(e)
  }
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
      const dec_payload_json = JSON.stringify(JSON.parse(dec_payload_cut), null, 2);
      return dec_payload_json;
    } catch (e) {
      console.log(e);
      return dec_payload_cut;
    }
  } catch (e) {
    console.log(e);
  }
}
