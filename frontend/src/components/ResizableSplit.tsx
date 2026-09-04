import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'

const STORAGE_KEY = 'nexus.architect.chatWidth'

export default function ResizableSplit({
  left,
  right,
  defaultWidth = 340,
  minWidth = 260,
  maxWidth = 640,
}: {
  left: ReactNode
  right: ReactNode
  defaultWidth?: number
  minWidth?: number
  maxWidth?: number
}) {
  const [width, setWidth] = useState(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY)
      if (saved) {
        const n = Number(saved)
        if (Number.isFinite(n)) return Math.min(maxWidth, Math.max(minWidth, n))
      }
    } catch {
      /* ignore */
    }
    return defaultWidth
  })
  const dragging = useRef(false)
  const startX = useRef(0)
  const startW = useRef(width)

  const onMove = useCallback(
    (event: MouseEvent) => {
      if (!dragging.current) return
      const next = Math.min(maxWidth, Math.max(minWidth, startW.current + event.clientX - startX.current))
      setWidth(next)
    },
    [maxWidth, minWidth],
  )

  const onUp = useCallback(() => {
    if (!dragging.current) return
    dragging.current = false
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
    try {
      localStorage.setItem(STORAGE_KEY, String(width))
    } catch {
      /* ignore */
    }
  }, [width])

  useEffect(() => {
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [onMove, onUp])

  return (
    <div className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
      <div className="flex h-full min-h-0 flex-shrink-0 flex-col overflow-hidden" style={{ width }}>
        {left}
      </div>
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize chat panel"
        title="Drag to resize"
        className="group relative z-10 w-1.5 shrink-0 cursor-col-resize bg-white/5 transition-colors hover:bg-primary-fixed-dim/40"
        onMouseDown={(event) => {
          dragging.current = true
          startX.current = event.clientX
          startW.current = width
          document.body.style.cursor = 'col-resize'
          document.body.style.userSelect = 'none'
        }}
      >
        <div className="absolute inset-y-0 -left-1 -right-1" />
        <div className="absolute left-1/2 top-1/2 h-10 w-0.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-white/20 group-hover:bg-primary-fixed-dim/80" />
      </div>
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">{right}</div>
    </div>
  )
}
