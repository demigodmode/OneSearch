// Copyright (C) 2026 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

import { describe, expect, it } from 'vitest'
import html from '../../index.html?raw'

describe('index.html', () => {
  it('loads nothing from another host', () => {
    const external = [...html.matchAll(/(?:href|src)="(?:https?:)?\/\/[^"]+"/g)].map((m) => m[0])

    expect(external).toEqual([])
  })
})
