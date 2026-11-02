// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import {
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from 'react'
import { useNavigate } from 'react-router-dom'
import {
  getToken,
  setToken,
  clearToken,
  getCurrentUser,
  login as apiLogin,
  logout as apiLogout,
  setup as apiSetup,
  changePassword as apiChangePassword,
  getAuthStatus,
} from '@/lib/api'
import type { User, LoginRequest, SetupRequest } from '@/types/api'
import { AuthContext, type AuthContextType } from '@/contexts/AuthContextValue'

interface AuthProviderProps {
  children: ReactNode
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [setupRequired, setSetupRequired] = useState(false)
  const navigate = useNavigate()

  const checkAuth = useCallback(async () => {
    setIsLoading(true)
    try {
      // First check if setup is required
      const authStatus = await getAuthStatus()
      setSetupRequired(authStatus.setup_required)

      if (authStatus.setup_required) {
        setUser(null)
        setIsLoading(false)
        return
      }

      // Check if we have a token
      const token = getToken()
      if (!token) {
        setUser(null)
        setIsLoading(false)
        return
      }

      // Validate token by fetching current user
      const currentUser = await getCurrentUser()
      setUser(currentUser)
    } catch {
      // Token is invalid or expired
      clearToken()
      setUser(null)
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    // Initial auth state comes from token/API state outside React.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    checkAuth()
  }, [checkAuth])

  const login = async (data: LoginRequest) => {
    const response = await apiLogin(data)
    setToken(response.access_token)
    const currentUser = await getCurrentUser()
    setUser(currentUser)
    navigate('/')
  }

  const logout = async () => {
    try {
      await apiLogout()
    } catch {
      // Ignore errors, just clear token
    }
    clearToken()
    setUser(null)
    navigate('/login')
  }

  const setup = async (data: SetupRequest) => {
    const response = await apiSetup(data)
    setToken(response.access_token)
    setSetupRequired(false)
    const currentUser = await getCurrentUser()
    setUser(currentUser)
    navigate('/')
  }

  // The old session is ended server-side, so swap in the fresh token and reload the user.
  // Once the server has accepted the change, a failed reload must not look like a failed change.
  const changePassword = async (currentPassword: string, newPassword: string) => {
    const response = await apiChangePassword({ current_password: currentPassword, new_password: newPassword })
    setToken(response.access_token)
    try {
      const currentUser = await getCurrentUser()
      setUser(currentUser)
    } catch {
      setUser((previous) => (previous ? { ...previous, must_change_password: false } : previous))
    }
  }

  const value: AuthContextType = {
    user,
    isAuthenticated: !!user,
    isLoading,
    setupRequired,
    login,
    logout,
    setup,
    changePassword,
    checkAuth,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
