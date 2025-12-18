// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { useState } from 'react'

function App() {
  const [count, setCount] = useState(0)

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="text-center">
        <h1 className="text-4xl font-bold text-gray-900 mb-4">OneSearch</h1>
        <p className="text-gray-600 mb-8">
          Self-hosted search for your homelab
        </p>
        <button
          onClick={() => setCount((count) => count + 1)}
          className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
        >
          count is {count}
        </button>
        <p className="mt-4 text-sm text-gray-500">
          Frontend is running! Backend components coming soon.
        </p>
      </div>
    </div>
  )
}

export default App
