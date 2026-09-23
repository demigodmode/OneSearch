import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, decodeText, getDocumentDownloadLink, getDocumentRawText } from './api'

const json = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))
const bytes = (data: Uint8Array, status = 200) => Promise.resolve(new Response(data as BodyInit, { status }))
const link = { url: '/api/documents/doc-1/download?token=t', expires_in: 60, filename: 'notes.md' }

describe('document API', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
  })

  it('surfaces the message from structured error details', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementationOnce(() =>
      json({ detail: { code: 'agent_offline', message: 'Remote agent is unavailable' } }, 409),
    )

    await expect(getDocumentDownloadLink('doc-1')).rejects.toMatchObject({
      message: 'Remote agent is unavailable',
      status: 409,
    })
  })

  it('fetches the original file through a download link', async () => {
    const raw = '---\ntitle: Notes\n---\n\n# Body\n'
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockImplementationOnce(() => json(link))
      .mockImplementationOnce(() => bytes(new TextEncoder().encode(raw)))

    await expect(getDocumentRawText('doc-1', 25 * 1024 * 1024)).resolves.toBe(raw)
    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/documents/doc-1/download-link', expect.objectContaining({ method: 'POST' }))
    expect(fetchMock).toHaveBeenNthCalledWith(2, link.url)
  })

  it('gives a friendlier message when the file fetch itself fails', async () => {
    vi.spyOn(globalThis, 'fetch')
      .mockImplementationOnce(() => json(link))
      .mockImplementationOnce(() => Promise.reject(new TypeError('Failed to fetch')))

    const error = await getDocumentRawText('doc-1', 25 * 1024 * 1024).catch((e) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error.message).toBe("Couldn't reach the server to load the original file")
  })

  it('rejects with 413 when Content-Length says the file on disk outgrew the limit', async () => {
    vi.spyOn(globalThis, 'fetch')
      .mockImplementationOnce(() => json(link))
      .mockImplementationOnce(() =>
        Promise.resolve(
          new Response(new ReadableStream({ start: (controller) => controller.close() }), {
            status: 200,
            headers: { 'Content-Length': String(30 * 1024 * 1024) },
          }),
        ),
      )

    const error = await getDocumentRawText('doc-1', 25 * 1024 * 1024).catch((e) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(413)
    expect(error.message).toBe('This file is now over the preview size limit. Download it to see the original.')
  })

  it('rejects with 413 and cancels the stream when a body without Content-Length exceeds the limit', async () => {
    const cancel = vi.fn()
    const chunk = new Uint8Array(1024 * 1024).fill(97) // 1MB of "a"
    let sent = 0

    vi.spyOn(globalThis, 'fetch')
      .mockImplementationOnce(() => json(link))
      .mockImplementationOnce(() =>
        Promise.resolve(
          new Response(
            new ReadableStream({
              pull(controller) {
                sent += 1
                controller.enqueue(chunk)
                if (sent >= 4) controller.close()
              },
              cancel,
            }),
            { status: 200 },
          ),
        ),
      )

    const error = await getDocumentRawText('doc-1', 2 * 1024 * 1024).catch((e) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(413)
    expect(cancel).toHaveBeenCalled()
  })

  it('reports download failures without touching the session', async () => {
    localStorage.setItem('onesearch_token', 'session')
    vi.spyOn(globalThis, 'fetch')
      .mockImplementationOnce(() => json(link))
      .mockImplementationOnce(() => json({ detail: { code: 'download_token_expired', message: 'Download token expired' } }, 401))

    const error = await getDocumentRawText('doc-1', 25 * 1024 * 1024).catch((e) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error.message).toBe('Download token expired')
    expect(localStorage.getItem('onesearch_token')).toBe('session')
  })

  it('joins 422 validation errors into a single message', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementationOnce(() =>
      json(
        {
          detail: [
            { loc: ['body', 'name'], msg: 'Field required', type: 'missing' },
            { loc: ['body', 'root_path'], msg: 'Field required', type: 'missing' },
          ],
        },
        422,
      ),
    )

    await expect(getDocumentDownloadLink('doc-1')).rejects.toMatchObject({
      message: 'Field required; Field required',
      status: 422,
    })
  })

  it('decodes utf-8 and falls back to latin-1', () => {
    expect(decodeText(new TextEncoder().encode('café').buffer)).toBe('café')
    expect(decodeText(new Uint8Array([0x63, 0x61, 0x66, 0xe9]).buffer)).toBe('café')
  })
})
