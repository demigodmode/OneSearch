import { afterEach, describe, expect, it, vi } from 'vitest'
import { updateAgentProcessingMode } from './api'

describe('agent API contracts', () => {
  afterEach(() => vi.restoreAllMocks())

  it('persists the selected default processing mode with the agent update route', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ id: 'agent-1', default_processing_mode: 'on_server' }), { status: 200 })
    )

    await updateAgentProcessingMode('agent-1', 'on_server')

    expect(fetchMock).toHaveBeenCalledWith('/api/agents/agent-1', expect.objectContaining({
      method: 'PATCH', body: JSON.stringify({ default_processing_mode: 'on_server' }),
    }))
  })
})
