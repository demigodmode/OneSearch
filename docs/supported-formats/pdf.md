# PDF Documents

PDF file support in OneSearch.

!!! note "Coming Soon"
    Detailed format documentation coming soon.

## Features

- Text extraction via pypdf
- Metadata extraction (title, author, page count)
- Size limits configurable via `MAX_PDF_FILE_SIZE_MB`
- Timeout protection for large/corrupted files

## Limitations

- No OCR support (yet)
- Password-protected PDFs are skipped
