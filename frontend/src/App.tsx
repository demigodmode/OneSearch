// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { Suspense, lazy } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from './contexts/AuthContext'
import { ThemeProvider } from './contexts/ThemeContext'
import { SearchSettingsProvider } from './contexts/SearchSettingsContext'
import ProtectedRoute from './components/ProtectedRoute'
import MainLayout from './components/MainLayout'
import AdminLayout from './components/AdminLayout'
import SearchPage from './pages/SearchPage'
import SourcesPage from './pages/admin/SourcesPage'
import StatusPage from './pages/admin/StatusPage'
import SettingsPage from './pages/admin/SettingsPage'
import LoginPage from './pages/LoginPage'
import SetupPage from './pages/SetupPage'

// Lazy-load DocumentPage — it pulls in react-syntax-highlighter + react-markdown (~400KB)
const DocumentPage = lazy(() => import('./pages/DocumentPage'))

function App() {
  return (
    <ThemeProvider>
    <AuthProvider>
    <SearchSettingsProvider>
      <Routes>
        {/* Public auth routes */}
        <Route path="/login" element={<LoginPage />} />
        <Route path="/setup" element={<SetupPage />} />

        {/* Protected main search route */}
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <MainLayout />
            </ProtectedRoute>
          }
        >
          <Route index element={<SearchPage />} />
          <Route path="document/:id" element={<Suspense fallback={null}><DocumentPage /></Suspense>} />
        </Route>

        {/* Protected admin routes */}
        <Route
          path="/admin"
          element={
            <ProtectedRoute>
              <AdminLayout />
            </ProtectedRoute>
          }
        >
          <Route index element={<Navigate to="/admin/sources" replace />} />
          <Route path="sources" element={<SourcesPage />} />
          <Route path="status" element={<StatusPage />} />
          <Route path="settings" element={<SettingsPage />} />
        </Route>

        {/* Catch-all 404 */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </SearchSettingsProvider>
    </AuthProvider>
    </ThemeProvider>
  )
}

export default App
