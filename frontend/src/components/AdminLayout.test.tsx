import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import AdminLayout from './AdminLayout'

let enabled = false
vi.mock('@/contexts/useAuth', () => ({ useAuth: () => ({ user: null, logout: vi.fn() }) }))
vi.mock('@/hooks/useApi', () => ({ useAppSettings: () => ({ data: { remote_agents_enabled: enabled } }) }))

describe('AdminLayout remote navigation', () => {
  it('hides Agents while disabled and shows it once enabled', () => {
    const { rerender } = render(<MemoryRouter><AdminLayout /></MemoryRouter>)
    expect(screen.queryByText('Agents')).not.toBeInTheDocument()
    enabled = true
    rerender(<MemoryRouter><AdminLayout /></MemoryRouter>)
    expect(screen.getByText('Agents')).toBeInTheDocument()
  })
})
