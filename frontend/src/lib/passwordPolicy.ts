// Copyright (C) 2026 demigodmode
// SPDX-License-Identifier: AGPL-3.0-only

export const MIN_PASSWORD_LENGTH = 8

export const PASSWORD_LENGTH_HINT = `At least ${MIN_PASSWORD_LENGTH} characters`

/** Returns the error message for a new password, or null when it is acceptable. */
export function validateNewPassword(password: string): string | null {
  return password.length < MIN_PASSWORD_LENGTH
    ? `Password must be at least ${MIN_PASSWORD_LENGTH} characters`
    : null
}
