// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import {
  createContext,
  useContext,
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
  getAuthStatus,
} from '@/lib/api'
import type { User, LoginRequest, SetupRequest } from '@/types/api'

interface AuthContextType {
  user: User | null
  isAuthenticated: boolean
  isLoading: boolean
  setupRequired: boolean
  login: (data: LoginRequest) => Promise<void>
  logout: () => Promise<void>
  setup: (data: SetupRequest) => Promise<void>
  checkAuth: () => Promise<void>
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

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
    } catch (error) {
      // Token is invalid or expired
      clearToken()
      setUser(null)
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
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

  const value: AuthContextType = {
    user,
    isAuthenticated: !!user,
    isLoading,
    setupRequired,
    login,
    logout,
    setup,
    checkAuth,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
