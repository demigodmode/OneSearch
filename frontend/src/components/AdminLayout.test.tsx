import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AdminLayout from './AdminLayout'

let enabled = false
vi.mock('@/contexts/useAuth', () => ({ useAuth: () => ({ user: null, logout: vi.fn() }) }))
vi.mock('@/hooks/useApi', () => ({ useAppSettings: () => ({ data: { remote_agents_enabled: enabled } }) }))

describe('AdminLayout navigation', () => {
  beforeEach(() => {
    enabled = false
  })

  it('shows the Users link', () => {
    render(<MemoryRouter><AdminLayout /></MemoryRouter>)
    expect(screen.getByText('Users')).toBeInTheDocument()
  })

  it('links the Audit log page', () => {
    render(<MemoryRouter><AdminLayout /></MemoryRouter>)
    expect(screen.getByRole('link', { name: 'Audit log' })).toHaveAttribute('href', '/admin/audit')
  })

  it('keeps Sources, Status, Users, Audit log, Agents, Settings in that order', () => {
    enabled = true
    render(<MemoryRouter><AdminLayout /></MemoryRouter>)
    const labels = within(screen.getByRole('navigation')).getAllByRole('link').map((link) => link.textContent)
    expect(labels).toEqual(['Sources', 'Status', 'Users', 'Audit log', 'Agents', 'Settings'])
  })

  it('hides Agents while disabled and shows it once enabled', () => {
    const { rerender } = render(<MemoryRouter><AdminLayout /></MemoryRouter>)
    expect(screen.queryByText('Agents')).not.toBeInTheDocument()
    enabled = true
    rerender(<MemoryRouter><AdminLayout /></MemoryRouter>)
    expect(screen.getByText('Agents')).toBeInTheDocument()
  })
})
