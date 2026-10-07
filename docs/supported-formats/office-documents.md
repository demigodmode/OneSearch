# Office Documents

OneSearch supports modern Microsoft Office formats and indexes them as separate document types.

## Word (`.docx`)

Indexed as `docx`.

Extracts:

- paragraph text
- table text
- document metadata when available

## Excel (`.xlsx`)

Indexed as `xlsx`.

Extracts:

- workbook sheets
- cell values
- sheet names and counts

To keep huge spreadsheets from getting silly, extraction is capped at 10,000 rows and 100 columns per sheet.

## PowerPoint (`.pptx`)

Indexed as `pptx`.

Extracts:

- slide text
- speaker notes
- presentation metadata when available

## RTF (`.rtf`)

Indexed as `rtf`.

Extracts the readable text, with the RTF formatting codes stripped out. The title is the filename, and no document metadata is read.

RTF counts as a text file for limits: it uses the text size limit and `TEXT_EXTRACTION_TIMEOUT`, not the Office ones below.

## Limits

Office extraction uses the Office size limit shown in **Admin → Settings → Indexing**. `MAX_OFFICE_FILE_SIZE_MB` provides the default value, and `OFFICE_EXTRACTION_TIMEOUT` controls how long extraction can run.

Password-protected or corrupt files are handled as extraction failures. OneSearch keeps going and records enough metadata to show what failed.

## Not supported

Old binary Office formats are not handled by these extractors:

- `.doc`
- `.xls`
- `.ppt`

Convert those to modern formats if you want full-text indexing.
