# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

# Unified multi-stage build for OneSearch
# Combines frontend, backend, and CLI into a single image

# =============================================================================
# Stage 1: Build Frontend
# =============================================================================
FROM docker.io/library/node:22-alpine AS frontend-builder

WORKDIR /app

# Copy dependency files
COPY frontend/package.json frontend/package-lock.json ./

# Install dependencies
RUN npm ci

# Copy source code
COPY frontend/ .

# Build production bundle
RUN npm run build

# =============================================================================
# Stage 2: Build Backend + CLI
# =============================================================================
FROM docker.io/library/python:3.13-slim AS backend-builder

# Install uv for fast package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy workspace root files
COPY pyproject.toml uv.lock ./

# Copy backend, CLI, and shared protocol packages
COPY backend/ ./backend/
COPY cli/ ./cli/
COPY shared/ ./shared/

# Install all workspace packages to user directory
RUN uv pip install --system --no-editable ./shared ./backend ./cli

# =============================================================================
# Stage 3: Meilisearch binary
# =============================================================================
FROM docker.io/getmeili/meilisearch:v1.12 AS meilisearch-runtime

# =============================================================================
# Stage 4: ffprobe for audio/video metadata
# =============================================================================
# Built from the official FFmpeg source release. No external libraries and no
# --enable-gpl, so the result is LGPL v2.1+. Only what's needed to read metadata
# from the media formats OneSearch indexes gets compiled in, which keeps the
# build short and the binary small.
FROM docker.io/library/python:3.13-slim AS ffprobe-builder

ARG FFMPEG_VERSION=9.0.2
ARG FFMPEG_SHA256=8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e

RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential ca-certificates curl xz-utils && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /build
RUN curl -fsSL -o ffmpeg.tar.xz "https://ffmpeg.org/releases/ffmpeg-${FFMPEG_VERSION}.tar.xz" && \
    echo "${FFMPEG_SHA256}  ffmpeg.tar.xz" | sha256sum -c - && \
    tar -xf ffmpeg.tar.xz --strip-components=1 && \
    ./configure \
        --disable-everything \
        --disable-autodetect \
        --disable-programs \
        --enable-ffprobe \
        --disable-doc \
        --disable-network \
        --disable-debug \
        --disable-asm \
        --disable-avdevice \
        --disable-avfilter \
        --disable-swscale \
        --disable-swresample \
        --enable-protocol=file \
        --enable-demuxer=mov,matroska,avi,mp3,flac,ogg,wav,aac \
        --enable-parser=h264,hevc,mpeg4video,mpegvideo,vp8,vp9,av1,aac,aac_latm,mpegaudio,flac,vorbis,opus,ac3 \
        --enable-decoder=h264,hevc,mpeg4,mpeg2video,vp8,vp9,aac,mp3,flac,vorbis,opus,ac3,eac3,alac,pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le,pcm_u8,pcm_s16be,pcm_alaw,pcm_mulaw && \
    make -j"$(nproc)" ffprobe && \
    install -D -m 0755 ffprobe /out/bin/ffprobe && \
    install -D -m 0644 COPYING.LGPLv2.1 /out/licenses/COPYING.LGPLv2.1 && \
    install -D -m 0644 LICENSE.md /out/licenses/LICENSE.md && \
    printf 'ffprobe from FFmpeg %s, built from https://ffmpeg.org/releases/ffmpeg-%s.tar.xz\nBuild flags are in the OneSearch Dockerfile: https://github.com/demigodmode/OneSearch\n' \
        "${FFMPEG_VERSION}" "${FFMPEG_VERSION}" > /out/licenses/SOURCE

# =============================================================================
# Stage 5: Runtime
# =============================================================================
FROM docker.io/library/python:3.13-slim

# Install runtime services, healthcheck curl, and exiftool for RAW metadata probing
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        nginx \
        supervisor \
        curl \
        libimage-exiftool-perl && \
    rm -rf /var/lib/apt/lists/* && \
    mkdir -p /var/log/supervisor

# Create non-root user for uvicorn
RUN useradd -m -u 1000 onesearch && \
    mkdir -p /app/data && \
    chown -R onesearch:onesearch /app

WORKDIR /app

# Copy installed Python packages from builder
COPY --from=backend-builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=backend-builder /usr/local/bin /usr/local/bin

# Copy Meilisearch binary and Alpine runtime libs for opt-in managed mode
COPY --from=ffprobe-builder /out/bin/ffprobe /usr/local/bin/ffprobe
COPY --from=ffprobe-builder /out/licenses /usr/share/licenses/ffmpeg
COPY --from=meilisearch-runtime /bin/meilisearch /usr/local/bin/meilisearch
COPY --from=meilisearch-runtime /lib/ld-musl-*.so.1 /lib/
COPY --from=meilisearch-runtime /lib/libc.musl-*.so.1 /lib/
COPY --from=meilisearch-runtime /usr/lib/libgcc_s.so.1 /usr/lib/libgcc_s.so.1

# Copy backend application code
COPY --chown=onesearch:onesearch backend/ ./backend/

# Copy frontend build
COPY --from=frontend-builder /app/dist ./frontend/

# Copy configuration files
COPY nginx.conf /etc/nginx/nginx.conf
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Copy and set up runtime scripts
COPY entrypoint.sh /app/entrypoint.sh
COPY start-backend.sh /app/start-backend.sh
RUN chmod +x /app/entrypoint.sh /app/start-backend.sh

# Fix nginx permissions (Debian uses www-data, not nginx)
RUN mkdir -p /var/cache/nginx /var/log/nginx && \
    chown -R www-data:www-data /var/cache/nginx && \
    chown -R www-data:www-data /var/log/nginx && \
    touch /var/run/nginx.pid && \
    chown -R www-data:www-data /var/run/nginx.pid

# Create data directories with correct permissions
RUN mkdir -p /app/data /app/meili_data && chown -R onesearch:onesearch /app/data /app/meili_data

# Expose port (nginx listens on 8000)
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://127.0.0.1:8000/api/health || exit 1

# Run entrypoint (migrations + supervisord)
ENTRYPOINT ["/app/entrypoint.sh"]
