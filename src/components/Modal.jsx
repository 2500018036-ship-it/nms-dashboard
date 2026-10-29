import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'

export function Modal({ title, children, footer, onClose, size = 'lg' }) {
  const ref = useRef(null)
  useEffect(() => {
    const dialog = ref.current; const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'; dialog.showModal()
    return () => { dialog.close(); document.body.style.overflow = overflow }
  }, [])
  return createPortal(<dialog ref={ref} className="modal show nms-modal" aria-label={title} onCancel={(e) => { e.preventDefault(); onClose() }} onClick={(e) => { if (e.target === ref.current) onClose() }}><div className={`modal-dialog modal-dialog-centered modal-dialog-scrollable ${size === 'lg' ? 'modal-lg' : ''}`}><div className="modal-content"><div className="modal-header"><h2 className="modal-title fs-5">{title}</h2><button type="button" className="btn-close" aria-label="Tutup modal" onClick={onClose} /></div><div className="modal-body">{children}</div>{footer && <div className="modal-footer">{footer}</div>}</div></div></dialog>, document.body)
}

export function Confirmation({ title, children, onClose, onConfirm, busy, confirmLabel = 'Konfirmasi', danger = false, confirmDisabled = false }) {
  return <Modal title={title} onClose={busy ? () => {} : onClose} size="sm" footer={<><button className="btn btn-secondary" disabled={busy} onClick={onClose}>Batal</button><button className={`btn btn-${danger ? 'danger' : 'primary'}`} disabled={busy || confirmDisabled} onClick={onConfirm}>{busy ? 'Memproses…' : confirmLabel}</button></>}>{children}</Modal>
}
