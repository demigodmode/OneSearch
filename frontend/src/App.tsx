// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { Routes, Route } from 'react-router-dom'
import MainLayout from './components/MainLayout'
import AdminLayout from './components/AdminLayout'
import SearchPage from './pages/SearchPage'
import SourcesPage from './pages/admin/SourcesPage'
import StatusPage from './pages/admin/StatusPage'

function App() {
  return (
    <Routes>
      {/* Main search route */}
      <Route path="/" element={<MainLayout />}>
        <Route index element={<SearchPage />} />
      </Route>

      {/* Admin routes */}
      <Route path="/admin" element={<AdminLayout />}>
        <Route path="sources" element={<SourcesPage />} />
        <Route path="status" element={<StatusPage />} />
      </Route>
    </Routes>
  )
}

export default App
