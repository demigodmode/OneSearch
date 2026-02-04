# Office Documents

Microsoft Office document support in OneSearch.

!!! note "Coming Soon"
    Detailed format documentation coming soon.

## Supported Formats

### Word (.docx)
- Paragraph text extraction
- Table content extraction
- Document metadata

### Excel (.xlsx)
- All sheets indexed
- Cell values extracted
- Workbook metadata

### PowerPoint (.pptx)
- Slide text extraction
- Speaker notes
- Presentation metadata

## Configuration

- `MAX_OFFICE_FILE_SIZE_MB` - Max file size (default: 50MB)
- `OFFICE_EXTRACTION_TIMEOUT` - Extraction timeout

## Limitations

- Old formats (.doc, .xls, .ppt) not supported (yet)
- Password-protected files are skipped
- Embedded objects not extracted
