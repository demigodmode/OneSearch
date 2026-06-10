# Audio & Video Media

Audio and video files are indexed as `media`.

## Extensions

- `.mp4`
- `.mkv`
- `.mov`
- `.avi`
- `.mp3`
- `.flac`
- `.m4a`
- `.ogg`
- `.wav`

## What OneSearch extracts

When media metadata is set to Auto and `ffprobe` is available, OneSearch can index:

- title, artist, album, and date tags
- container format
- duration
- bitrate
- video/audio codecs
- dimensions and frame rate
- sample rate and channel count

If `ffprobe` is missing or fails, files fall back to metadata-only indexing.

## Settings

```env
MEDIA_METADATA_MODE=auto
MEDIA_PROBE_MAX_SIZE_MB=0
```

`MEDIA_PROBE_MAX_SIZE_MB=0` means there is no size cap for probing. The timeout still applies.

## Search behavior

Media files usually do not have full text. Search works best for filenames, paths, source names, and extracted tags such as artist/title/album.
