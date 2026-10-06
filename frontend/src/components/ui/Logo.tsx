/**
 * The Origin mark.
 *
 * A ring with a filled centre: an "O" that also reads as a point radiating
 * outward, which is what the product is - a retrieval point that everything
 * else is measured from. Two faint outer arcs give it depth without turning to
 * noise at 32px.
 *
 * Theme-aware by construction. The tile uses a Tailwind gradient with `dark:`
 * overrides rather than a prop, so it follows the theme automatically and stays
 * consistent with how every other surface in the app switches. Light mode runs
 * a deeper indigo so the white ring keeps contrast against the fill; dark mode
 * lifts toward a brighter violet and adds a glow, because a dark tile on a dark
 * page needs separation that light mode does not.
 */

import { cn } from '../../lib/utils'

export function LogoTile({
  size = 32,
  className,
  markClassName,
}: {
  /** Rendered height in px; width matches. */
  size?: number
  className?: string
  markClassName?: string
}) {
  // Radius tracks size so a 32px tile and a 56px one share proportions.
  const radius = size >= 48 ? 'rounded-2xl' : size >= 36 ? 'rounded-xl' : 'rounded-lg'

  return (
    <div
      data-testid="origin-logo"
      className={cn(
        'grid shrink-0 place-items-center bg-gradient-to-br text-white',
        'from-[#4f46e5] to-[#7c3aed]',
        'dark:from-[#6366f1] dark:to-[#a855f7]',
        'shadow-card dark:shadow-[0_0_0_1px_rgba(168,85,247,0.25),0_6px_18px_-6px_rgba(129,122,255,0.55)]',
        radius,
        className,
      )}
      style={{ width: size, height: size }}
      aria-hidden
    >
      <OriginMark className={markClassName} px={size} />
    </div>
  )
}

/**
 * The bare mark, without the tile. Used at sizes where the surrounding chrome
 * already provides contrast.
 */
export function OriginMark({ px = 24, className }: { px?: number; className?: string }) {
  // Stroke and dot scale with the box so the proportions hold at any size.
  const stroke = px <= 20 ? 2.9 : px <= 28 ? 2.4 : 2.1
  const dot = px <= 20 ? 2.5 : px <= 28 ? 3.1 : 3.6
  const halo = px <= 20 ? 0.42 : 0.34

  return (
    <svg
      viewBox="0 0 24 24"
      width={px}
      height={px}
      fill="none"
      className={className}
    >
      {/* Halo arcs: two partial rings suggesting something radiating out. */}
      <path
        d="M12 1.6a10.4 10.4 0 0 1 10.4 10.4"
        stroke="currentColor"
        strokeOpacity={halo}
        strokeWidth="1.1"
        strokeLinecap="round"
      />
      <path
        d="M12 22.4A10.4 10.4 0 0 1 1.6 12"
        stroke="currentColor"
        strokeOpacity={halo}
        strokeWidth="1.1"
        strokeLinecap="round"
      />
      {/* The O. */}
      <circle cx="12" cy="12" r="7.1" stroke="currentColor" strokeWidth={stroke} />
      {/* The origin point. */}
      <circle cx="12" cy="12" r={dot} fill="currentColor" />
    </svg>
  )
}