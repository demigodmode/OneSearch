# PDF Documents

PDFs are indexed as `pdf` documents.

## What OneSearch extracts

OneSearch uses `pypdf` to extract:

- text from pages
- page count
- PDF metadata such as title, author, subject, creator, and producer when present

The document title comes from PDF metadata first, then falls back to the filename.

## Search and preview

Extracted text is searchable like any other document. The document page shows the extracted text and metadata.

PDF text extraction depends on the PDF. A born-digital PDF usually works well. A scanned PDF with only images will not have searchable text unless OCR support is added later.

## Limits

PDF extraction is bounded by the PDF size limit shown in **Admin → Settings → Indexing**. `MAX_PDF_FILE_SIZE_MB` provides the default value, and `PDF_EXTRACTION_TIMEOUT` controls how long extraction can run.

Encrypted PDFs are tried with an empty password. If that fails, the file is recorded as an extraction failure and can still show basic filename/path metadata.

## Not supported yet

- OCR for scanned PDFs
- password-protected PDFs that require a real password
