/**
 * Ambient drifting light for the auth screen.
 *
 * Why this is CSS and not a GIF: an animated GIF is the wrong tool here on
 * every axis that matters for a full-screen background. It would be a
 * multi-megabyte asset on the critical path of first paint, quantised to a
 * fixed palette that bands badly across a full screen of smooth gradient, fixed
 * at one resolution so it is either soft on a Retina display or wasteful on a
 * 4K one, and unable to respond to the light/dark theme at all - the one thing
 * this background must do. Gradients cost a few hundred bytes of CSS and stay
 * sharp at any size.
 *
 * Performance notes, since this animates continuously:
 * - Only `transform` is animated, so the layers are promoted to the compositor
 *   and each frame is a composited move. No layout, no paint.
 * - No `filter: blur()`. Softness comes from the radial gradient's transparent
 *   stop, which is free; a blur filter would rasterise a full-screen layer every
 *   frame.
 * - Durations are 24-40s. Ambient motion should be unnoticeable per-frame; a
 *   faster loop reads as decoration and pulls attention from the form.
 * - `prefers-reduced-motion` is honoured globally in index.css, which collapses
 *   these to a static frame.
 */

import { cn } from '../../lib/utils'

/**
 * Static fractal-noise tile. Large soft gradients band visibly on 8-bit
 * displays, especially in dark mode; a grain overlay breaks the bands up. It is
 * a data-URI SVG so it costs no extra request.
 */
const GRAIN =
  "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='140' height='140'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='3'/%3E%3C/filter%3E%3Crect width='140' height='140' filter='url(%23n)' opacity='0.5'/%3E%3C/svg%3E\")"

/** One drifting light source. */
function Light({
  className,
  duration,
  animation,
  background,
}: {
  className?: string
  duration: number
  animation: string
  background: string
}) {
  return (
    <div
      className={cn('absolute will-change-transform', className)}
      style={{
        animation: `${animation} ${duration}s ease-in-out infinite`,
        background,
      }}
    />
  )
}

export function AmbientBackdrop({ className }: { className?: string }) {
  return (
    <div
      aria-hidden
      data-testid="ambient-backdrop"
      className={cn('pointer-events-none absolute inset-0 overflow-hidden', className)}
    >
      {/* Light mode: a faint cool wash. Kept well below the contrast needed to
          read the form, since this sits behind text. */}
      <Light
        animation="origin-drift-a"
        duration={28}
        className="-left-[18%] -top-[22%] h-[62vmax] w-[62vmax] rounded-full opacity-55 dark:opacity-70"
        background="radial-gradient(circle, rgb(99 102 241 / 0.20) 0%, rgb(99 102 241 / 0.07) 38%, transparent 66%)"
      />
      <Light
        animation="origin-drift-b"
        duration={34}
        className="-bottom-[26%] -right-[14%] h-[54vmax] w-[54vmax] rounded-full opacity-50 dark:opacity-65"
        background="radial-gradient(circle, rgb(168 85 247 / 0.18) 0%, rgb(168 85 247 / 0.06) 40%, transparent 68%)"
      />
      <Light
        animation="origin-drift-c"
        duration={40}
        className="left-[24%] top-[16%] h-[40vmax] w-[40vmax] rounded-full opacity-40 dark:opacity-55"
        background="radial-gradient(circle, rgb(56 189 248 / 0.14) 0%, transparent 62%)"
      />

      {/* Vignette. Deepens the corners so the drifting light reads as light
          falling on a surface rather than as coloured blobs on a flat page. */}
      <div
        className="absolute inset-0"
        style={{
          animation: 'origin-breathe 18s ease-in-out infinite',
          background:
            'radial-gradient(120% 90% at 50% 40%, transparent 34%, rgb(2 6 23 / 0.16) 78%, rgb(2 6 23 / 0.30) 100%)',
        }}
      />

      {/* Banding guard. */}
      <div
        className="absolute inset-0 opacity-[0.035] mix-blend-overlay dark:opacity-[0.055]"
        style={{ backgroundImage: GRAIN, backgroundSize: '140px 140px' }}
      />
    </div>
  )
}