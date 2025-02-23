Google Play Books downloader for interoperability purposes. Each page is downloaded as an image, it's up to you to build
a PDF from them, do OCR, and add metadata.

**Why**:

- Google Play Books has [two reading modes](https://support.google.com/googleplay/answer/185545):
    - `Flowing text`: EPUB file. You can download it from your Google Play Books library, when available.
    - `Original Pages`: PDF file. Usually provided to Google by the book publisher, or sometimes scanned by Google
      themselves (where each page is a big image). You can download this PDF from Google Play Books, but *only* if
      Google (arbitrarily) decides that its size is small enough.
- The Google Play Reader app isn't available on all platforms (e.g. e-ink tablets) but fortunately you can download an
  EPUB or a PDF file. You can then read the downloaded book on any platform, provided that it supports the Adobe Digital
  Editions DRM.
- Problem: Many PDFs are not available for download because Google unilaterally decides that they
  are [“large book files”](https://support.google.com/googleplay/answer/179863?hl=en#:~:text=You%20can%27t%20download%20some%20large%20book%20files) (
  vague term for which they provide no definition). Due to that you can't read the book (that you bought!) on the
  platform of your choice.

**Note**: this script only works for books that have the “Original Pages” viewing option.

# Prerequisites

- Install [Python](https://www.python.org/downloads/)
  and [Poetry](https://python-poetry.org/docs/#installing-with-the-official-installer).
- Download and extract
  the [project repository](https://github.com/devnoname120/google-play-book-downloader/archive/refs/heads/main.zip).
- Run `poetry install` inside the extracted project repository folder in order to download the dependencies.

# Usage (PDF download)

- Get the cookies and headers from Google Play Books:
    1) Open a new private/incognito browser window.
    2) Go to https://play.google.com/books and log in.
    3) Open dev console, network tab.
    4) Click on a random link in the page.
    5) Right-click on the corresponding request in the dev console and then `Copy as cURL`.
    6) In the `google-play-book-downloader` project folder, create the file `curl.txt` if it doesn't exist. If it already exists, delete its content.
    7) Paste your clipboard in the `curl.txt` file and save.
    8) Close the private browser window (and don't log out of your account before doing that).
- **Note:** you will need to redo the previous steps every time your cookies expire (they usually expire pretty quickly unfortunately).
- Run the script from the project folder:

```shell
poetry run python google-play-book-downloader-pdf.py
```

You will find the downloaded book pages in the `books/[BOOK_ID]` folder.

# Recommended next steps:

1) **Optimize the resulting images**:

   a) Run [pngquant](https://github.com/kornelski/pngquant). It does high-quality lossy compression (40-70%) on the PNG
   images by optimizing the color palette:
    ```shell
    pngquant -fv --ext=.png --skip-if-larger --speed=1 --quality=95-100 *.png
    ```

   b) (Optional) Run [oxipng](https://github.com/shssoichiro/oxipng). It does additional lossless compression (3-5%) on
   the PNG images produced by pngquant:
    ```shell
    oxipng --dir . --strip safe --interlace 0 -o 4 *.png
    ```

2) **Build a PDF**

   This command will merge all the pages into a PDF, add metadata (book title, date, authors, etc.), and a table
   of contents.

   Run the following command (replace `[BOOK_ID]` with the ID of the book):

    ```shell
    poetry run play-book-pdf-build books/[BOOK_ID]
    ```

3) **OCR and optimize the PDF** using Adobe Acrobat Pro:

   a) Open the PDF.

   b) **[Menu]** `Tools` → `Scan` → `OCR`.

   c) **[Scan & OCR toolbar]** → `Settings`:
    - Tick `All pages`.
    - Set `Document Language` to the correct one (e.g. English).
    - Set `Output` to `Searchable Image (Exact)` (**important!**).
    - Press `OK`.

   d) **[Scan & OCR toolbar]** → `Recognize Text`.

   e) **[Menu]** `File` → `Save as Other` → `Optimized PDF…`.

    - Untick everything, except section **[Cleanup]**.
    - Section **[Cleanup]**
        - Tick `Optimize the PDF for fast web view` and untick everything else. This option makes Adobe Acrobat
          reorganize the structure of the PDF to be linear. This enables PDF viewers to quickly display the PDF while
          it's still downloading in the background.
        - Set `Object compression options` to `Leave compression unchanged`.
    - Click on OK.


# Usage (EPUB download)

There is an *extremely experimental* EPUB downloader in the project as well. For now it just downloads all the pages of a given book in the HTML format and embeds all the resources (images, fonts, etc.) directly in the HTML files as base64. EPUB is not reconstructed yet.

No support yet as it's experimental! Please don't open issues on GitHub regarding the EPUB downloader.

- First run the PDF download for the book (**mandatory**). See the section above on how to do that.

- Open `google-play-book-downloader-epub.py` and edit the following constants:
    - `BOOK_ID`: the ID of the book. You can find it in the URL to the book page. Example: `BwCMEAAAQBAJ`
    - `headers`/`cookies`: the headers and cookies that are necessary to send requests on your behalf. Here is how to get
      them:
        1) Go to https://play.google.com/books and log in.
        2) Open dev console, network tab.
        3) Click on a random link in the page.
        4) Right-click on the corresponding request in the dev console and then `Copy as cURL`.
        5) Go to https://curlconverter.com/python/ and paste your clipboard in the input box.
        6) From the Python code that was generated just copy the `cookies` and `headers` variables and replace them in `google-play-downloader-epub.py`.

- Run the script from the repository folder:

```shell
poetry run python google-play-book-downloader-epub.py
```

You will find the downloaded book pages as HTML in the `books/[BOOK_ID]/segments` folder. The output is very crude and EPUBs are not reconstructed.
