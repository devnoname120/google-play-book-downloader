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

  const realsize_bin = bytearray.subarray(16, 20);

  // Has custom padding, includes the real size so that we can cut the output to remove the padding.
  const buf_actualsize = Buffer.from(realsize_bin).readUInt32LE();
  console.log(`\n[size_uint]: ${buf_actualsize}`);

  const data = bytearray.subarray(20);
  // console.log(`\n[data]: ${data.length}`);
  // console.log(data);

  try {
    const dec = aes.dec(data, aes_key, iv, 'binary', 'binary', 'aes-128-cbc', false);

    const size_computed = buf_actualsize;
    const end = size_computed - 1;

    console.log(`[size_computed]: ${size_computed}`);
    console.log(`[end]: ${end}`);

    const dec_payload = Buffer.from(dec).subarray(0, end).toString('utf-8');
    // console.log(dec_payload);

    try {
      const dec_payload_json = JSON.stringify(JSON.parse(dec_payload), null, 2);
      return dec_payload_json;
    } catch (e) {
      // console.log(`Unparsed JSON payload: ${dec_payload}`);
      // console.log(`\n\n[[CUT PAYLOAD]]: ${dec_payload}\n\n`);
      // console.log(`\n\n[[FULL PAYLOAD]]: ${Buffer.from(dec).subarray(0, buf_actualsize + 16).toString('utf-8')}\n\n`);
      console.log(e);
      return dec_payload;
    }
  } catch (e) {
    console.log(e);
  }
}
