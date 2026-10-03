// Copyright (C) 2025 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

export const RAW_PAGE_CHARS = 20_000
export const RAW_PAGE_LINES = 200

export type RawTextPage = {
  start: number
  end: number
  startingLineNumber: number
  endingLineNumber: number
  continuesFromPrevious: boolean
  continuesOnNext: boolean
}

function nextRawToken(content: string, offset: number) {
  const character = content.charCodeAt(offset)
  if (character === 13 && content.charCodeAt(offset + 1) === 10) return { end: offset + 2, lineBreak: true }
  if (character === 10) return { end: offset + 1, lineBreak: true }
  if (character >= 0xd800 && character <= 0xdbff && content.charCodeAt(offset + 1) >= 0xdc00 && content.charCodeAt(offset + 1) <= 0xdfff) {
    return { end: offset + 2, lineBreak: false }
  }
  return { end: offset + 1, lineBreak: false }
}

export function buildRawTextPages(content: string): RawTextPage[] {
  if (content.length === 0) {
    return [{ start: 0, end: 0, startingLineNumber: 1, endingLineNumber: 1, continuesFromPrevious: false, continuesOnNext: false }]
  }

  const pages: RawTextPage[] = []
  let start = 0
  let lineNumber = 1

  while (start < content.length) {
    let end = start
    let completedLines = 0

    while (end < content.length) {
      if (completedLines >= RAW_PAGE_LINES) break
      const token = nextRawToken(content, end)
      const tokenLength = token.end - end
      if (end > start && end - start + tokenLength > RAW_PAGE_CHARS) break

      end = token.end
      if (token.lineBreak) completedLines += 1
    }

    const continuesFromPrevious = start > 0 && content.charCodeAt(start - 1) !== 10
    const continuesOnNext = end < content.length && content.charCodeAt(end - 1) !== 10
    pages.push({
      start,
      end,
      startingLineNumber: lineNumber,
      endingLineNumber: lineNumber + completedLines,
      continuesFromPrevious,
      continuesOnNext,
    })
    start = end
    lineNumber += completedLines
  }

  return pages
}
