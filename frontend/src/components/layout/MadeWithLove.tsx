/**
 * The credit line shown at the bottom of the sidebar and on the auth screen.
 *
 * The heart is an inline SVG rather than the "♥" character because glyph
 * rendering of text hearts differs per platform - emoji presentation selects can
 * turn U+2665 into an outlined emoji that loses the red entirely. An explicit
 * path is the only way to guarantee the colour.
 */

import { cn } from '../../lib/utils'

export function MadeWithLove({ className }: { className?: string }) {
  return (
    <p
      data-testid="made-with-love"
      className={cn(
        'flex select-none items-center justify-center gap-1.5 text-[11px] leading-none text-ink-faint',
        className,
      )}
    >
      <span>Made with</span>
      <svg
        viewBox="0 0 24 24"
        width="11"
        height="11"
        aria-label="love"
        role="img"
        className="shrink-0 text-red-500"
      >
        <path
          fill="currentColor"
          d="M12 21s-7.5-4.7-9.6-9.2C.7 8.2 2.4 4.5 6 4.5c2.1 0 3.6 1.2 4.3 2.4h3.4C14.4 5.7 15.9 4.5 18 4.5c3.6 0 5.3 3.7 3.6 7.3C19.5 16.3 12 21 12 21z"
        />
      </svg>
      <span>by Parth</span>
    </p>
  )
}