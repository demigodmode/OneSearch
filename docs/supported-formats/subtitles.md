# Subtitles

Subtitle files are indexed as `subtitle`.

## Extensions

- `.srt`
- `.vtt`
- `.ass`

## What OneSearch extracts

OneSearch strips timing and formatting data, then indexes the readable transcript text.

It also records:

- subtitle format
- cue count

Encoding detection is used when UTF-8 does not work cleanly.

## Search behavior

This is useful for finding dialogue across downloaded videos, lectures, conference talks, or media libraries with sidecar subtitle files.

## Limits

Subtitles use the text extraction limit shown in **Admin → Settings → Indexing**. `MAX_TEXT_FILE_SIZE_MB` provides the default value, and `TEXT_EXTRACTION_TIMEOUT` controls how long extraction can run.
