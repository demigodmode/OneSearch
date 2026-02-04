// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { Routes, Route } from 'react-router-dom'
import { AuthProvider } from './contexts/AuthContext'
import ProtectedRoute from './components/ProtectedRoute'
import MainLayout from './components/MainLayout'
import AdminLayout from './components/AdminLayout'
import SearchPage from './pages/SearchPage'
import DocumentPage from './pages/DocumentPage'
import SourcesPage from './pages/admin/SourcesPage'
import StatusPage from './pages/admin/StatusPage'
import LoginPage from './pages/LoginPage'
import SetupPage from './pages/SetupPage'

function App() {
  return (
    <AuthProvider>
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
          <Route path="document/:id" element={<DocumentPage />} />
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
          <Route path="sources" element={<SourcesPage />} />
          <Route path="status" element={<StatusPage />} />
        </Route>
      </Routes>
    </AuthProvider>
  )
}

export default App
