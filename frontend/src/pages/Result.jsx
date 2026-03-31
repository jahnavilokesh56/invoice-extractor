import { useLocation, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ArrowLeft, Copy, Check, Download, FileText } from 'lucide-react'
import { useState, useEffect, useRef } from 'react'
import { toast } from 'react-hot-toast'
import styles from './Result.module.css'

const FIELD_LABELS = {
  invoice_number:    'Invoice Number',
  invoice_date:      'Invoice Date',
  vendor_name:       'Vendor Name',
  vendor_gstin:      'Vendor GSTIN',
  vendor_address:    'Vendor Address',
  customer_name:     'Customer Name',
  customer_gstin:    'Customer GSTIN',
  customer_address:  'Customer Address',
  place_of_supply:   'Place of Supply',
  sac_code:          'SAC Code',
  mode_of_transport: 'Mode of Transport',
  pan:               'PAN',
  subtotal:          'Subtotal (₹)',
  central_tax:       'Central Tax',
  state_tax:         'State Tax',
  igst_rate:         'IGST Rate',
  igst_amount:       'IGST Amount (₹)',
  total_gst:         'Total GST (₹)',
  grand_total:       'Grand Total (₹)',
  source:            'Extraction Source',
}

const MONEY_FIELDS = ['subtotal', 'igst_amount', 'total_gst', 'grand_total', 'central_tax', 'state_tax']

const SECTIONS = [
  { label: 'Invoice Info',     keys: ['invoice_number','invoice_date','sac_code','mode_of_transport','place_of_supply','source'] },
  { label: 'Vendor Details',   keys: ['vendor_name','vendor_gstin','vendor_address','pan'] },
  { label: 'Customer Details', keys: ['customer_name','customer_gstin','customer_address'] },
  { label: 'Financials',       keys: ['subtotal','central_tax','state_tax','igst_rate','igst_amount','total_gst','grand_total'] },
]

export default function Result() {
  const { state } = useLocation()
  const navigate = useNavigate()
  const [copied, setCopied] = useState(false)
  const [pdfUrl, setPdfUrl] = useState(null)
  const objectUrlRef = useRef(null)

  useEffect(() => {
  if (state?.fileObject) {
    const url = URL.createObjectURL(state.fileObject)
    objectUrlRef.current = url
    setPdfUrl(url)
  } else if (state?.filename) {
    // Fallback: load from backend if navigated from History
    setPdfUrl(`http://localhost:8000/uploads/${state.filename}`)
  }
  return () => {
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current)
  }
}, [state?.fileObject, state?.filename])
  if (!state?.result) {
    return (
      <div className={styles.empty}>
        <p>No result found. Please extract an invoice first.</p>
        <button className={styles.backBtn} onClick={() => navigate('/')}>Go Back</button>
      </div>
    )
  }

  const { result, filename } = state

  const copyJSON = () => {
    navigator.clipboard.writeText(JSON.stringify(result, null, 2))
    setCopied(true)
    toast.success('Copied to clipboard!')
    setTimeout(() => setCopied(false), 2000)
  }

  const downloadJSON = () => {
    const blob = new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = (filename || 'invoice').replace(/\.\w+$/, '.json')
    a.click()
    toast.success('JSON downloaded!')
  }

  const formatValue = (key, value) => {
    if (!value && value !== 0) return <span className={styles.empty2}>—</span>
    if (MONEY_FIELDS.includes(key) && typeof value === 'number') {
      return <span className={styles.money}>₹ {value.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</span>
    }
    return String(value)
  }

  return (
    <div className={styles.page}>
      {/* Top bar */}
      <div className={styles.topBar}>
        <button className={styles.back} onClick={() => navigate('/')}>
          <ArrowLeft size={15} /> Back
        </button>
        <div className={styles.fileChip}>
          <FileText size={13} /> {filename}
        </div>
        <div className={styles.actions}>
          <button className={styles.iconBtn} onClick={copyJSON} title="Copy JSON">
            {copied ? <Check size={15} /> : <Copy size={15} />}
            {copied ? 'Copied' : 'Copy JSON'}
          </button>
          <button className={styles.iconBtn} onClick={downloadJSON} title="Download JSON">
            <Download size={15} /> Download
          </button>
        </div>
      </div>

      {/* Split layout */}
      <div className={styles.splitLayout}>

        {/* LEFT — PDF Viewer */}
        <div className={styles.pdfPanel}>
          <div className={styles.pdfHeader}>
            <FileText size={13} />
            <span>Invoice Preview</span>
          </div>
          {pdfUrl ? (
  filename?.match(/\.(png|jpg|jpeg|tiff|tif)$/i) ? (
    <img
      src={pdfUrl}
      alt="Invoice"
      style={{ width: '100%', height: '100%', objectFit: 'contain', background: '#fff' }}
    />
  ) : (
    <iframe
      src={pdfUrl}
      className={styles.pdfFrame}
      title="Invoice PDF"
    />
  )
) : (
  <div className={styles.pdfFallback}>
    <FileText size={40} opacity={0.3} />
    <p>PDF preview not available</p>
    <span>Re-upload the invoice to see a preview</span>
  </div>
)}
        </div>

        {/* RIGHT — Extracted data */}
        <div className={styles.dataPanel}>
          <h2 className={styles.pageTitle}>Extracted Invoice Data</h2>

          {/* Highlight cards */}
          <motion.div
            className={styles.highlights}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4 }}
          >
            {[
              { label: 'Invoice No', value: result.invoice_number || '—', accent: true },
              { label: 'Date',       value: result.invoice_date   || '—' },
              { label: 'Total',      value: result.grand_total ? `₹${Number(result.grand_total).toLocaleString('en-IN')}` : '—', accent: true },
              { label: 'GST',        value: result.total_gst ? `₹${Number(result.total_gst).toLocaleString('en-IN')}` : '—' },
            ].map(({ label, value, accent }) => (
              <div key={label} className={`${styles.highlight} ${accent ? styles.highlightAccent : ''}`}>
                <span className={styles.hlLabel}>{label}</span>
                <span className={styles.hlValue}>{value}</span>
              </div>
            ))}
          </motion.div>

          {/* Sections */}
          <div className={styles.sections}>
            {SECTIONS.map(({ label, keys }, si) => (
              <motion.div
                key={label}
                className={styles.section}
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.1 + si * 0.07 }}
              >
                <h3 className={styles.sectionTitle}>{label}</h3>
                <div className={styles.fields}>
                  {keys.map(key => (
                    result[key] !== undefined && (
                      <div key={key} className={styles.field}>
                        <span className={styles.fieldLabel}>{FIELD_LABELS[key] || key}</span>
                        <span className={styles.fieldValue}>{formatValue(key, result[key])}</span>
                      </div>
                    )
                  ))}
                </div>
              </motion.div>
            ))}

            {/* Line items */}
            {result.line_items && result.line_items.length > 0 && (
              <motion.div
                className={styles.section}
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.4 }}
              >
                <h3 className={styles.sectionTitle}>Line Items ({result.line_items.length})</h3>
                <div className={styles.tableWrap}>
                  <table className={styles.table}>
                    <thead>
                      <tr>
                        {Object.keys(result.line_items[0]).map(k => (
                          <th key={k}>{k.replace(/_/g,' ')}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {result.line_items.map((item, i) => (
                        <tr key={i}>
                          {Object.values(item).map((v, j) => (
                            <td key={j}>{String(v)}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </motion.div>
            )}

            {/* Raw JSON */}
            <motion.div
              className={styles.section}
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.5 }}
            >
              <h3 className={styles.sectionTitle}>Raw JSON Output</h3>
              <pre className={styles.json}>{JSON.stringify(result, null, 2)}</pre>
            </motion.div>
          </div>
        </div>
      </div>
    </div>
  )
}