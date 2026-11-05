import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import './Tooltip.css'

/**
 * Tooltip component - rich hover/focus tooltip for dense reference data
 *
 * Built for the planner, where badge tiers and animation requirements need to
 * be readable without expanding a card and losing your place in the grid.
 *
 * - Opens on hover AND keyboard focus, so it is not mouse-only.
 * - Portalled to <body> and positioned with fixed coordinates, so it is never
 *   clipped by a scrolling panel or an `overflow: hidden` ancestor.
 * - Flips above the trigger when there is no room below, and clamps
 *   horizontally to stay on screen.
 * - Escape dismisses; touch devices get it on tap via focus.
 *
 * @param {React.ReactNode} content - tooltip body (rich nodes allowed)
 * @param {React.ReactNode} children - the trigger element(s)
 * @param {string} className - extra classes for the trigger wrapper
 */
export default function Tooltip({ content, children, className = '' }) {
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState({ top: 0, left: 0, placement: 'bottom' })
  const triggerRef = useRef(null)
  const tipRef = useRef(null)
  const id = useId()

  const place = useCallback(() => {
    const trigger = triggerRef.current
    const tip = tipRef.current
    if (!trigger || !tip) return

    const t = trigger.getBoundingClientRect()
    const tip_ = tip.getBoundingClientRect()
    const GAP = 8
    const MARGIN = 8

    // Prefer below; flip above when it would overflow the viewport bottom.
    let placement = 'bottom'
    let top = t.bottom + GAP
    if (top + tip_.height > window.innerHeight - MARGIN && t.top - GAP - tip_.height > MARGIN) {
      placement = 'top'
      top = t.top - GAP - tip_.height
    }

    // Centre on the trigger, then clamp into the viewport.
    let left = t.left + t.width / 2 - tip_.width / 2
    left = Math.max(MARGIN, Math.min(left, window.innerWidth - tip_.width - MARGIN))

    setPos({ top, left, placement })
  }, [])

  useLayoutEffect(() => {
    if (open) place()
  }, [open, place])

  useEffect(() => {
    if (!open) return
    const onScrollOrResize = () => place()
    const onKeyDown = (e) => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('scroll', onScrollOrResize, true)
    window.addEventListener('resize', onScrollOrResize)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      window.removeEventListener('scroll', onScrollOrResize, true)
      window.removeEventListener('resize', onScrollOrResize)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open, place])

  return (
    <span
      ref={triggerRef}
      className={`tooltip-trigger ${className}`}
      tabIndex={0}
      aria-describedby={open ? id : undefined}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
    >
      {children}
      {open && createPortal(
        <div
          id={id}
          ref={tipRef}
          role="tooltip"
          className={`tooltip tooltip--${pos.placement}`}
          style={{ top: `${pos.top}px`, left: `${pos.left}px` }}
        >
          {content}
        </div>,
        document.body
      )}
    </span>
  )
}
