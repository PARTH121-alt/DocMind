/**
 * localStorage keys, with migration from the pre-rename `docmind.*` names.
 *
 * The product was renamed from DocMind to Origin. Renaming the storage keys
 * without a migration would log every existing user out and reset their theme
 * and active collection, so reads fall back to the old key and writes go
 * straight to the new one. The fallback can be dropped once no live install is
 * carrying `docmind.*` data.
 */

const LEGACY_PREFIX = 'docmind.'
const PREFIX = 'origin.'

/** Read a namespaced key, transparently upgrading a legacy value. */
export function readKey(name: string): string | null {
  const current = localStorage.getItem(PREFIX + name)
  if (current !== null) return current

  const legacy = localStorage.getItem(LEGACY_PREFIX + name)
  if (legacy === null) return null

  // Move it across so the next read is a direct hit, then drop the old copy.
  localStorage.setItem(PREFIX + name, legacy)
  localStorage.removeItem(LEGACY_PREFIX + name)
  return legacy
}

export function writeKey(name: string, value: string): void {
  localStorage.setItem(PREFIX + name, value)
}

export function removeKey(name: string): void {
  localStorage.removeItem(PREFIX + name)
  localStorage.removeItem(LEGACY_PREFIX + name)
}

/** Namespaced event name for cross-component CustomEvents. */
export function eventName(name: string): string {
  return `${PREFIX}${name}`
}