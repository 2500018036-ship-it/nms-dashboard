import { useLayoutEffect, useRef } from 'react'
import { createPortal } from 'react-dom'

export function FloatingMenu({ open, anchorRef, onClose, children, width = 300, matchAnchorWidth = false, autoFocus = true, className = '', as: Element = 'ul' }) {
  const root = useRef(null)
  useLayoutEffect(() => {
    if (!open || !root.current || !anchorRef.current) return
    const place = () => {
      const menu = root.current; const anchor = anchorRef.current
      if (!menu || !anchor) return
      const rect = anchor.getBoundingClientRect(); const viewport = window.visualViewport
      const x = viewport?.offsetLeft || 0; const y = viewport?.offsetTop || 0
      const vw = viewport?.width || window.innerWidth; const vh = viewport?.height || window.innerHeight
      const available = Math.max(120, vw - 24)
      const w = Math.min(matchAnchorWidth ? Math.max(rect.width, 240) : width, available)
      menu.style.width = w + 'px'; menu.style.maxHeight = Math.max(100, vh - 24) + 'px'
      const h = Math.min(menu.scrollHeight, vh - 24)
      const left = Math.max(x + 12, Math.min(matchAnchorWidth ? rect.left : rect.right - w, x + vw - w - 12))
      const preferred = rect.bottom + 8 + h <= y + vh - 12 ? rect.bottom + 8 : rect.top - h - 8
      const top = Math.max(y + 12, Math.min(preferred, y + vh - h - 12))
      Object.assign(menu.style, { left: left + 'px', top: top + 'px', visibility: 'visible' })
    }
    const outside = (event) => { if (!root.current?.contains(event.target) && !anchorRef.current?.contains(event.target)) onClose() }
    place()
    const resize = new ResizeObserver(place); resize.observe(root.current); resize.observe(anchorRef.current)
    window.addEventListener('resize', place); window.addEventListener('scroll', place, true)
    window.visualViewport?.addEventListener('resize', place)
    document.addEventListener('pointerdown', outside)
    return () => { resize.disconnect(); window.removeEventListener('resize', place); window.removeEventListener('scroll', place, true); window.visualViewport?.removeEventListener('resize', place); document.removeEventListener('pointerdown', outside) }
  }, [open, anchorRef, onClose, width, matchAnchorWidth])
  useLayoutEffect(() => {
    if (open && autoFocus) root.current?.querySelector('a,button:not(:disabled)')?.focus({ preventScroll: true })
  }, [open, autoFocus])
  if (!open) return null
  return createPortal(<Element ref={root} data-nms-floating-menu="true" className={'dropdown-menu show shadow-lg nms-floating-menu ' + className} style={{ position: 'fixed', visibility: 'hidden' }} onKeyDown={(event) => {
    const entries = [...root.current.querySelectorAll('a,button:not(:disabled)')]
    const current = entries.indexOf(document.activeElement)
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); entries[(current + (event.key === 'ArrowDown' ? 1 : -1) + entries.length) % entries.length]?.focus() }
    if (event.key === 'Escape') { event.preventDefault(); onClose(); anchorRef.current?.focus() }
  }}>{children}</Element>, document.body)
}
