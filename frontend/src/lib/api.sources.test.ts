import { afterEach, describe, expect, it, vi } from 'vitest'
import { testSourcePath } from './api'

const pending = {
  path: '/srv/docs', ok: false, exists: false, is_directory: false, readable: false,
  inside_allowed_roots: true, allowed_roots: ['/srv/docs'], looks_like_host_path: false,
  message: 'Remote path validation is queued.', job_id: 'job-1', status: 'pending',
}

const response = (body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status: 200 }))

describe('source path test API', () => {
  afterEach(() => vi.restoreAllMocks())

  it('polls a queued remote path test through completion', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockImplementationOnce(() => response(pending))
      .mockImplementationOnce(() => response({ ...pending, status: 'running' }))
      .mockImplementationOnce(() => response({ ...pending, status: 'completed', ok: true, exists: true, is_directory: true, readable: true, message: 'Ready' }))

    const result = await testSourcePath(
      { root_path: '/srv/docs', location_type: 'agent', agent_id: 'agent-1' },
      { pollIntervalMs: 0, pollTimeoutMs: 1_000 },
    )

    expect(result.ok).toBe(true)
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/sources/test-path/job-1', expect.any(Object))
  })

  it('returns the completed failed result without further polling', async () => {
    vi.spyOn(globalThis, 'fetch')
      .mockImplementationOnce(() => response(pending))
      .mockImplementationOnce(() => response({ ...pending, status: 'failed', message: 'Could not validate' }))

    const result = await testSourcePath(
      { root_path: '/srv/docs', location_type: 'agent', agent_id: 'agent-1' },
      { pollIntervalMs: 0, pollTimeoutMs: 1_000 },
    )

    expect(result.status).toBe('failed')
    expect(result.ok).toBe(false)
  })

  it('fails with a clear error when remote validation times out', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => response(pending))

    await expect(testSourcePath(
      { root_path: '/srv/docs', location_type: 'agent', agent_id: 'agent-1' },
      { pollIntervalMs: 0, pollTimeoutMs: 0 },
    )).rejects.toEqual(expect.objectContaining({ message: 'Remote path validation timed out.' }))
  })
})
