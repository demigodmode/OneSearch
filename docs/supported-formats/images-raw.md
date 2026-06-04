# Images & RAW Photos

Images are indexed as `image`; RAW photos are indexed as `raw_image`.

## Extensions

Browser-viewable images:

- `.jpg`, `.jpeg`, `.png`, `.webp`, `.gif`, `.tif`, `.tiff`

RAW formats:

- `.cr2`, `.cr3`, `.nef`, `.arw`, `.raf`, `.orf`, `.rw2`, `.dng`

## What OneSearch extracts

For normal images, OneSearch reads basic image metadata with Pillow:

- width and height
- image format
- common EXIF camera fields when present

For RAW files, OneSearch can use `exiftool` in Auto mode. The Docker image includes it.

RAW metadata can include camera make/model, lens, ISO, aperture, exposure time, focal length, dimensions, and date taken.

GPS metadata is off by default. Turn it on only if you want location data searchable.

## Previews

Image previews are authenticated and served only for indexed documents.

RAW previews use embedded JPEG previews when available. OneSearch does not decode RAW sensor data.

## Settings

Useful settings:

```env
RAW_METADATA_MODE=auto
RAW_METADATA_TIMEOUT_SECONDS=10
INDEX_GPS_METADATA=false
IMAGE_METADATA_MAX_SIZE_MB=100
SHOW_PREVIEWS=true
RAW_PREVIEW_ENABLED=true
MAX_PREVIEW_SIZE_MB=50
```

Most of these can also be changed in **Admin → Settings**.

## Failure behavior

If an image is too large or unreadable, OneSearch falls back to filename/path metadata where possible. That keeps the file searchable without failing the whole source.
