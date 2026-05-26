import { useLocation, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ArrowLeft, Copy, Check, Download, FileText, AlertCircle, FileJson, Pencil, X, Save, RotateCcw } from 'lucide-react'
import { useState, useEffect, useRef } from 'react'
import { toast } from 'react-hot-toast'
import styles from './Result.module.css'

const FIELD_LABELS = {
  invoice_number:    'Invoice Number',
  invoice_date:      'Invoice Date',
  vendor_name:       'Vendor Name',
  vendor_gstin:      'Vendor GSTIN',
  vendor_pan:        'Vendor PAN',
  vendor_address:    'Vendor Address',
  customer_name:     'Customer Name',
  customer_gstin:    'Customer GSTIN',
  customer_pan:      'Customer PAN',
  customer_address:  'Customer Address',
  place_of_supply:   'Place of Supply',
  sac_code:          'SAC Code',
  mode_of_transport: 'Mode of Transport',
  subtotal:          'Subtotal (₹)',
  freight_charges:   'Freight Charges (₹)',
  central_tax:       'Central Tax (CGST) (₹)',
  state_tax:         'State Tax (SGST) (₹)',
  igst_rate:         'IGST Rate',
  igst_amount:       'IGST Amount (₹)',
  total_gst:         'Total GST (₹)',
  grand_total:       'Grand Total (₹)',
  bank_name:         'Bank Name',
  bank_account_no:   'Bank Account No.',
  bank_ifsc:         'IFSC Code',
  bank_account_type: 'Account Type',
  source:            'Extraction Source',
  confidence_score:  'Confidence Score',
}

const MONEY_FIELDS = ['subtotal', 'freight_charges', 'igst_amount', 'total_gst', 'grand_total', 'central_tax', 'state_tax']
const NON_EDITABLE_FIELDS = ['source', 'confidence_score']

const SECTIONS = [
  { label: 'Invoice Info',     keys: ['invoice_number', 'invoice_date', 'sac_code', 'mode_of_transport', 'place_of_supply', 'source', 'confidence_score'] },
  { label: 'Vendor Details',   keys: ['vendor_name', 'vendor_gstin', 'vendor_pan', 'vendor_address'] },
  { label: 'Customer Details', keys: ['customer_name', 'customer_gstin', 'customer_pan', 'customer_address'] },
  { label: 'Financials',       keys: ['subtotal', 'freight_charges', 'central_tax', 'state_tax', 'igst_rate', 'igst_amount', 'total_gst', 'grand_total'] },
  { label: 'Bank Details',     keys: ['bank_name', 'bank_account_no', 'bank_ifsc', 'bank_account_type'] },
]

const isImageFile = (filename) =>
  /\.(png|jpg|jpeg|tiff|tif)$/i.test(filename ?? '')

const confidenceColor = (score) => {
  const n = Number(score)
  if (n >= 75) return '#22c55e'
  if (n >= 50) return '#f59e0b'
  return '#ef4444'
}

export default function Result() {
  const { state } = useLocation()
  const navigate  = useNavigate()

  const [copied,       setCopied]       = useState(false)
  const [pdfUrl,       setPdfUrl]       = useState(null)
  const [previewError, setPreviewError] = useState(false)

  const [editedResult,  setEditedResult]  = useState(null)
  const [editingKey,    setEditingKey]    = useState(null)
  const [editingValue,  setEditingValue]  = useState('')
  const [isDirty,       setIsDirty]       = useState(false)
  const inputRef = useRef(null)
  const objectUrlRef = useRef(null)

  useEffect(() => {
    if (state?.result) setEditedResult({ ...state.result })
  }, [state?.result])

  useEffect(() => {
    setPreviewError(false)
    if (state?.fileObject) {
      const url = URL.createObjectURL(state.fileObject)
      objectUrlRef.current = url
      setPdfUrl(url)
    } else if (state?.filename && state?.isSample) {
      setPdfUrl(`http://localhost:8001/sample-invoices/file/${encodeURIComponent(state.filename)}`)
    } else if (state?.filename && state?.hasPreview !== false) {
      setPdfUrl(`http://localhost:8001/uploads/${encodeURIComponent(state.filename)}`)
    } else {
      setPdfUrl(null)
    }
    return () => {
      if (objectUrlRef.current) { URL.revokeObjectURL(objectUrlRef.current); objectUrlRef.current = null }
    }
  }, [state?.fileObject, state?.filename, state?.hasPreview, state?.isSample])

  useEffect(() => {
    if (editingKey && inputRef.current) { inputRef.current.focus(); inputRef.current.select() }
  }, [editingKey])

  if (!state?.result || !editedResult) {
    return (
      <div className={styles.empty}>
        <AlertCircle size={36} strokeWidth={1.5} style={{ opacity: 0.4 }} />
        <p>No result found. Please extract an invoice first.</p>
        <button className={styles.backBtn} onClick={() => navigate('/')}>Go Back</button>
      </div>
    )
  }

  const { filename } = state

  const startEdit = (key, currentVal) => {
    if (NON_EDITABLE_FIELDS.includes(key)) return
    setEditingKey(key)
    setEditingValue(currentVal !== null && currentVal !== undefined ? String(currentVal) : '')
  }

  const commitEdit = () => {
    if (editingKey === null) return
    const oldVal = editedResult[editingKey]
    let newVal = editingValue
    if (MONEY_FIELDS.includes(editingKey) || editingKey === 'igst_rate') {
      const n = parseFloat(editingValue)
      newVal = isNaN(n) ? editingValue : n
    }
    if (String(newVal) !== String(oldVal)) {
      setEditedResult(prev => ({ ...prev, [editingKey]: newVal }))
      setIsDirty(true)
      toast.success(`Updated "${FIELD_LABELS[editingKey] || editingKey}"`)
    }
    setEditingKey(null)
    setEditingValue('')
  }

  const cancelEdit = () => { setEditingKey(null); setEditingValue('') }

  const resetAll = () => {
    setEditedResult({ ...state.result })
    setIsDirty(false)
    setEditingKey(null)
    toast('All edits reverted', { icon: '↩️' })
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); commitEdit() }
    if (e.key === 'Escape') cancelEdit()
  }

  const copyJSON = () => {
    navigator.clipboard.writeText(JSON.stringify(editedResult, null, 2))
    setCopied(true)
    toast.success('Copied to clipboard!')
    setTimeout(() => setCopied(false), 2000)
  }

  const downloadJSON = () => {
    const blob = new Blob([JSON.stringify(editedResult, null, 2)], { type: 'application/json' })
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement('a')
    a.href = url; a.download = (filename || 'invoice').replace(/\.\w+$/, '.json'); a.click()
    URL.revokeObjectURL(url)
    toast.success('JSON downloaded!')
  }

  const downloadCSV = async () => {
    try {
      const rows = [['Field', 'Value']]
      const flat = (obj, prefix = '') => {
        for (const [k, v] of Object.entries(obj || {})) {
          const key = prefix ? `${prefix}.${k}` : k
          if (Array.isArray(v)) {
            v.forEach((item, i) => {
              if (typeof item === 'object' && item !== null) flat(item, `${key}[${i}]`)
              else rows.push([`${key}[${i}]`, String(item ?? '')])
            })
          } else if (typeof v === 'object' && v !== null) { flat(v, key)
          } else { rows.push([key, String(v ?? '')]) }
        }
      }
      flat(editedResult)
      const csv = rows.map(r => r.map(c => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\r\n')
      const blob = new Blob([csv], { type: 'text/csv' })
      const url  = URL.createObjectURL(blob)
      const a    = document.createElement('a')
      a.href = url; a.download = (filename || 'invoice').replace(/\.\w+$/, '.csv'); a.click()
      URL.revokeObjectURL(url)
      toast.success('CSV downloaded!')
    } catch { toast.error('CSV export failed') }
  }

  const formatValue = (key, value) => {
    if (key === 'confidence_score') {
      const n = Number(value)
      return <span style={{ color: confidenceColor(n), fontWeight: 600 }}>{n}% {n >= 75 ? '✓ High' : n >= 50 ? '⚠ Medium' : '✗ Low'}</span>
    }
    if (!value && value !== 0) return <span className={styles.empty2}>—</span>
    if (MONEY_FIELDS.includes(key) && typeof value === 'number' && value > 0) {
      return <span className={styles.money}>₹ {value.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</span>
    }
    return String(value)
  }

  const wasEdited = (key) => String(editedResult[key]) !== String(state.result[key])

  const renderPreview = () => {
    if (!pdfUrl || previewError) {
      return (
        <div className={styles.pdfFallback}>
          <FileText size={40} opacity={0.3} />
          <p>{previewError ? 'Preview could not be loaded' : 'PDF preview not available'}</p>
          <span>{previewError ? 'The file may have been removed from the server' : 'Re-upload the invoice to see a preview'}</span>
        </div>
      )
    }
    if (isImageFile(filename)) {
      return <img src={pdfUrl} alt="Invoice" className={styles.previewImage} onError={() => setPreviewError(true)} />
    }
    return <iframe src={pdfUrl} className={styles.pdfFrame} title="Invoice PDF" onError={() => setPreviewError(true)} />
  }

  const hasBankDetails = ['bank_name','bank_account_no','bank_ifsc','bank_account_type'].some(k => editedResult[k])

  return (
    <div className={styles.page}>
      <div className={styles.topBar}>
        <button className={styles.back} onClick={() => navigate(-1)}><ArrowLeft size={15} /> Back</button>
        <div className={styles.fileChip}><FileText size={13} /><span className={styles.fileChipName}>{filename}</span></div>
        <div className={styles.actions}>
          {isDirty && (
            <button className={`${styles.iconBtn} ${styles.resetBtn}`} onClick={resetAll} title="Reset all edits">
              <RotateCcw size={15} /> Reset
            </button>
          )}
          <button className={styles.iconBtn} onClick={copyJSON} title="Copy JSON">
            {copied ? <Check size={15} /> : <Copy size={15} />}{copied ? 'Copied' : 'Copy JSON'}
          </button>
          <button className={styles.iconBtn} onClick={downloadJSON} title="Download JSON"><FileJson size={15} /> JSON</button>
          <button className={styles.iconBtn} onClick={downloadCSV} title="Download CSV"><Download size={15} /> CSV</button>
        </div>
      </div>

      <div className={styles.splitLayout}>
        <div className={styles.pdfPanel}>
          <div className={styles.pdfHeader}><FileText size={13} /><span>Invoice Preview</span></div>
          {renderPreview()}
        </div>

        <div className={styles.dataPanel}>
          <div className={styles.dataPanelHeader}>
            <h2 className={styles.pageTitle}>Extracted Invoice Data</h2>
            {isDirty && (
              <span className={styles.editBanner}><Pencil size={12} /> Edited — exports include your corrections</span>
            )}
          </div>

          <motion.div className={styles.highlights} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
            {[
              { label: 'Invoice No', value: editedResult.invoice_number || '—', accent: true },
              { label: 'Date',       value: editedResult.invoice_date   || '—' },
              { label: 'Total',      value: editedResult.grand_total ? `₹${Number(editedResult.grand_total).toLocaleString('en-IN')}` : '—', accent: true },
              { label: 'Confidence', value: editedResult.confidence_score ? `${editedResult.confidence_score}%` : '—' },
            ].map(({ label, value, accent }) => (
              <div key={label} className={`${styles.highlight} ${accent ? styles.highlightAccent : ''}`}>
                <span className={styles.hlLabel}>{label}</span>
                <span className={styles.hlValue}>{value}</span>
              </div>
            ))}
          </motion.div>

          <div className={styles.sections}>
            {SECTIONS.map(({ label, keys }, si) => {
              if (label === 'Bank Details' && !hasBankDetails) return null
              return (
                <motion.div key={label} className={styles.section} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 + si * 0.07 }}>
                  <h3 className={styles.sectionTitle}>{label}</h3>
                  <div className={styles.fields}>
                    {keys.map(key =>
                      editedResult[key] !== undefined ? (
                        <div key={key} className={`${styles.field} ${!NON_EDITABLE_FIELDS.includes(key) ? styles.fieldEditable : ''} ${wasEdited(key) ? styles.fieldModified : ''}`}>
                          <span className={styles.fieldLabel}>
                            {FIELD_LABELS[key] || key}
                            {wasEdited(key) && <span className={styles.modifiedDot} title="Manually edited">●</span>}
                          </span>

                          {editingKey === key ? (
                            <div className={styles.inlineEdit}>
                              {(key === 'vendor_address' || key === 'customer_address') ? (
                                <textarea ref={inputRef} className={styles.editTextarea} value={editingValue} onChange={e => setEditingValue(e.target.value)} onKeyDown={handleKeyDown} rows={3} />
                              ) : (
                                <input ref={inputRef} type={MONEY_FIELDS.includes(key) || key === 'igst_rate' ? 'number' : 'text'} className={styles.editInput} value={editingValue} onChange={e => setEditingValue(e.target.value)} onKeyDown={handleKeyDown} />
                              )}
                              <div className={styles.editActions}>
                                <button className={styles.saveBtn} onClick={commitEdit} title="Save (Enter)"><Save size={13} /> Save</button>
                                <button className={styles.cancelBtn} onClick={cancelEdit} title="Cancel (Esc)"><X size={13} /></button>
                              </div>
                            </div>
                          ) : (
                            <div className={`${styles.fieldValueWrap} ${!NON_EDITABLE_FIELDS.includes(key) ? styles.clickableValue : ''}`} onClick={() => startEdit(key, editedResult[key])} title={NON_EDITABLE_FIELDS.includes(key) ? '' : 'Click to edit'}>
                              <span className={styles.fieldValue}>{formatValue(key, editedResult[key])}</span>
                              {!NON_EDITABLE_FIELDS.includes(key) && <Pencil size={11} className={styles.editIcon} />}
                            </div>
                          )}
                        </div>
                      ) : null
                    )}
                  </div>
                </motion.div>
              )
            })}

            {editedResult.line_items?.length > 0 && (
              <motion.div className={styles.section} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.4 }}>
                <h3 className={styles.sectionTitle}>Line Items ({editedResult.line_items.length})</h3>
                <div className={styles.tableWrap}>
                  <table className={styles.table}>
                    <thead><tr>{Object.keys(editedResult.line_items[0]).map(k => <th key={k}>{k.replace(/_/g, ' ')}</th>)}</tr></thead>
                    <tbody>{editedResult.line_items.map((item, i) => <tr key={i}>{Object.values(item).map((v, j) => <td key={j}>{String(v)}</td>)}</tr>)}</tbody>
                  </table>
                </div>
              </motion.div>
            )}

            <motion.div className={styles.section} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.5 }}>
              <h3 className={styles.sectionTitle}>Raw JSON Output {isDirty && <span className={styles.jsonDirtyTag}>(edited)</span>}</h3>
              <pre className={styles.json}>{JSON.stringify(editedResult, null, 2)}</pre>
            </motion.div>
          </div>
        </div>
      </div>
    </div>
  )
}
