import { useEffect, useLayoutEffect, useRef } from 'react'
import { createPortal } from 'react-dom'

export function TopologyContextMenu({position,onClose,children}) {
  const ref=useRef(null)
  const close=useRef(onClose)
  useEffect(()=>{close.current=onClose},[onClose])
  useLayoutEffect(()=>{
    const menu=ref.current
    const box=menu.getBoundingClientRect()
    menu.style.left=Math.max(8,Math.min(position.x,window.innerWidth-box.width-8))+'px'
    menu.style.top=Math.max(8,Math.min(position.y,window.innerHeight-box.height-8))+'px'
    menu.focus()
    const outside=(event)=>{if(!menu.contains(event.target))close.current()}
    const escape=(event)=>{if(event.key==='Escape'){event.preventDefault();close.current()}}
    const resize=()=>close.current()
    document.addEventListener('pointerdown',outside);document.addEventListener('keydown',escape)
    window.addEventListener('resize',resize)
    return()=>{document.removeEventListener('pointerdown',outside);document.removeEventListener('keydown',escape);window.removeEventListener('resize',resize)}
  },[position])
  return createPortal(<div ref={ref} className="nms-topology-context" role="dialog" aria-label="Informasi dan tindakan topologi" tabIndex={-1}><button className="btn-close float-end" aria-label="Tutup menu perangkat" onClick={onClose}/>{children}</div>,document.body)
}
