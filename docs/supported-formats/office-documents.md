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
- workbook metadata

To keep huge spreadsheets from getting silly, extraction is capped at 10,000 rows and 100 columns per sheet.

## PowerPoint (`.pptx`)

Indexed as `pptx`.

Extracts:

- slide text
- speaker notes
- presentation metadata when available

## Limits

Office extraction uses:

```env
MAX_OFFICE_FILE_SIZE_MB=50
OFFICE_EXTRACTION_TIMEOUT=30
```

Password-protected or corrupt files are handled as extraction failures. OneSearch keeps going and records enough metadata to show what failed.

## Not supported

Old binary Office formats are not handled by these extractors:

- `.doc`
- `.xls`
- `.ppt`

Convert those to modern formats if you want full-text indexing.
