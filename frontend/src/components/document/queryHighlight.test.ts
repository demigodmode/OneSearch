import { afterEach, describe, expect, it, vi } from 'vitest'
import { RawQueryCursor } from './queryHighlight'

describe('RawQueryCursor', () => {
  afterEach(() => vi.restoreAllMocks())
  it('keeps ordinary global non-overlap alignment across boundaries and revisits', () => {
    const cursor = new RawQueryCursor('aaaaaa', 'aa')

    expect(cursor.rangesForPage(0, 0, 3)).toEqual([{ start: 0, end: 2 }, { start: 2, end: 3 }])
    expect(cursor.rangesForPage(1, 3, 6)).toEqual([{ start: 0, end: 1 }, { start: 1, end: 3 }])
    expect(cursor.rangesForPage(0, 0, 3)).toEqual([{ start: 0, end: 2 }, { start: 2, end: 3 }])
  })

  it('carries one long exact phrase through every touched page', () => {
    const cursor = new RawQueryCursor(`before ${'x'.repeat(20)} after`, 'xxxxxxxxxxxxxxxxxxxx')

    expect(cursor.rangesForPage(0, 0, 10)).toEqual([{ start: 7, end: 10 }])
    expect(cursor.rangesForPage(1, 10, 20)).toEqual([{ start: 0, end: 10 }])
    expect(cursor.rangesForPage(2, 20, 33)).toEqual([{ start: 0, end: 7 }])
  })

  it('uses fallback alternatives only when the full exact phrase is absent', () => {
    const cursor = new RawQueryCursor('alpha then BETA', 'alpha beta gamma')

    expect(cursor.rangesForPage(0, 0, 15)).toEqual([{ start: 0, end: 5 }, { start: 11, end: 15 }])
  })

  it('replays cached pages without consuming a suffix and carries a future pending match through untouched pages', () => {
    const content = `aa ${'x'.repeat(40)} aa ${'x'.repeat(40)} aa ${'x'.repeat(40)} later`
    const exec = vi.spyOn(RegExp.prototype, 'exec')
    const cursor = new RawQueryCursor(content, 'aa later')
    const targetCalls = () => exec.mock.calls.filter(([value]) => value === content).length

    expect(cursor.rangesForPage(0, 0, 20)).toEqual([{ start: 0, end: 2 }])
    expect(cursor.rangesForPage(1, 20, 40)).toEqual([])
    const callsBeforeReplay = targetCalls()
    expect(cursor.rangesForPage(0, 0, 20)).toEqual([{ start: 0, end: 2 }])
    expect(targetCalls()).toBe(callsBeforeReplay)

    expect(cursor.rangesForPage(2, 40, content.length)).toEqual([{ start: 4, end: 6 }, { start: 48, end: 50 }, { start: 92, end: 97 }])
  })

  it('keeps a late first match pending without executing the pattern for every preceding page', () => {
    const content = `${'x'.repeat(90)} target ${'x'.repeat(30)}`
    const exec = vi.spyOn(RegExp.prototype, 'exec')
    const cursor = new RawQueryCursor(content, 'target')
    const targetCalls = () => exec.mock.calls.filter(([value]) => value === content).length
    const afterConstruction = targetCalls()

    expect(cursor.rangesForPage(0, 0, 30)).toEqual([])
    expect(cursor.rangesForPage(1, 30, 60)).toEqual([])
    expect(cursor.rangesForPage(2, 60, 90)).toEqual([])
    expect(targetCalls()).toBe(afterConstruction)
    expect(cursor.rangesForPage(3, 90, content.length)).toEqual([{ start: 1, end: 7 }])
    expect(targetCalls()).toBe(afterConstruction + 1)
  })
})
