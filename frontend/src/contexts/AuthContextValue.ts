// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { createContext } from 'react'
import type { User, LoginRequest, SetupRequest } from '@/types/api'

export interface AuthContextType {
  user: User | null
  isAuthenticated: boolean
  isLoading: boolean
  setupRequired: boolean
  login: (data: LoginRequest) => Promise<void>
  logout: () => Promise<void>
  setup: (data: SetupRequest) => Promise<void>
  checkAuth: () => Promise<void>
}

export const AuthContext = createContext<AuthContextType | undefined>(undefined)
