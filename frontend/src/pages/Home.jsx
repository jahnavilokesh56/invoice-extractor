import { useState, useCallback, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useDropzone } from 'react-dropzone'
import { motion, AnimatePresence } from 'framer-motion'
import { toast } from 'react-hot-toast'
import {
  FileText, X, Zap, Loader2, ChevronRight, FileUp,
  FolderOpen, PlayCircle, ChevronDown, Download, FileJson,
  LayoutList, File
} from 'lucide-react'
import axios from 'axios'
import styles from './Home.module.css'

const API = 'http://localhost:8000'

// ── helpers ──────────────────────────────────────────────────────────────────
function saveHistory(entries) {
  const history = JSON.parse(localStorage.getItem('invoice_history') || '[]')
  entries.forEach(e => history.unshift(e))
  localStorage.setItem('invoice_history', JSON.stringify(history.slice(0, 50)))
}

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a   = document.createElement('a')
  a.href = url; a.download = filename; a.click()
  URL.revokeObjectURL(url)
}

// ── component ─────────────────────────────────────────────────────────────────
export default function Home() {
  const navigate = useNavigate()
  const [files,         setFiles]         = useState([])
  const [loading,       setLoading]       = useState(false)
  const [loadingAction, setLoadingAction] = useState('') // 'json' | 'csv' | 'extract'
  const [mode,          setMode]          = useState('single')   // 'single' | 'batch'
  const [sampleInvoices,setSampleInvoices]= useState([])
  const [samplesOpen,   setSamplesOpen]   = useState(false)
  const [sampleLoading, setSampleLoading] = useState(false)

  // load sample list once
  useEffect(() => {
    axios.get(`${API}/sample-invoices`)
      .then(r => setSampleInvoices(r.data.files || []))
      .catch(() => {})
  }, [])

  // ── dropzone ──────────────────────────────────────────────────────────────
  const onDrop = useCallback((accepted) => {
    const incoming = accepted.map(f => ({ file: f, id: Math.random().toString(36).slice(2) }))
    if (mode === 'single') {
      setFiles(incoming.slice(0, 1))
    } else {
      setFiles(prev => {
        const combined = [...prev, ...incoming]
        if (combined.length > 50) toast.error('Maximum 50 files — extras were ignored')
        return combined.slice(0, 50)
      })
    }
  }, [mode])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'application/pdf': ['.pdf'], 'image/*': ['.png', '.jpg', '.jpeg', '.tiff'] },
    maxFiles: mode === 'single' ? 1 : 50,
  })

  const removeFile = id => setFiles(prev => prev.filter(f => f.id !== id))

  const clearFiles = () => setFiles([])

  // ── single extract → view result ──────────────────────────────────────────
  const handleExtract = async () => {
    if (!files.length) { toast.error('Please upload at least one invoice'); return }
    setLoading(true); setLoadingAction('extract')
    try {
      if (mode === 'single') {
        const fd = new FormData()
        fd.append('file', files[0].file)
        const { data } = await axios.post(`${API}/extract`, fd)
        saveHistory([{ id: Date.now(), filename: files[0].file.name, data, date: new Date().toISOString(), hasPreview: true }])
        navigate('/result', { state: { result: data, filename: files[0].file.name, fileObject: files[0].file } })

      } else {
        const fd = new FormData()
        files.forEach(f => fd.append('files', f.file))
        const { data } = await axios.post(`${API}/extract-multiple`, fd)
        const ok  = data.results.filter(r => r.status === 'success')
        const bad = data.results.filter(r => r.status === 'error')
        if (ok.length)  toast.success(`Extracted ${ok.length} invoice${ok.length > 1 ? 's' : ''}`)
        if (bad.length) toast.error(`${bad.length} file${bad.length > 1 ? 's' : ''} failed`)
        saveHistory(ok.map(r => ({ id: Date.now() + Math.random(), filename: r.filename, data: r.data, date: new Date().toISOString(), hasPreview: true })))
        navigate('/history')
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Extraction failed. Is the backend running?')
    } finally {
      setLoading(false); setLoadingAction('')
    }
  }

  // ── download JSON ─────────────────────────────────────────────────────────
  const handleDownloadJSON = async () => {
    if (!files.length) { toast.error('Please upload at least one invoice'); return }
    setLoading(true); setLoadingAction('json')
    try {
      if (mode === 'single') {
        const fd = new FormData()
        fd.append('file', files[0].file)
        const { data } = await axios.post(`${API}/extract`, fd)
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
        triggerDownload(blob, files[0].file.name.replace(/\.\w+$/, '.json'))
        toast.success('JSON downloaded!')
      } else {
        const fd = new FormData()
        files.forEach(f => fd.append('files', f.file))
        const { data } = await axios.post(`${API}/export-json-batch`, fd, { responseType: 'blob' })
        triggerDownload(new Blob([data]), 'invoices_batch.json')
        toast.success('Batch JSON downloaded!')
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || 'JSON export failed')
    } finally {
      setLoading(false); setLoadingAction('')
    }
  }

  // ── download CSV ──────────────────────────────────────────────────────────
  const handleDownloadCSV = async () => {
    if (!files.length) { toast.error('Please upload at least one invoice'); return }
    setLoading(true); setLoadingAction('csv')
    try {
      if (mode === 'single') {
        const fd = new FormData()
        fd.append('file', files[0].file)
        const { data } = await axios.post(`${API}/export-csv`, fd, { responseType: 'blob' })
        triggerDownload(new Blob([data]), files[0].file.name.replace(/\.\w+$/, '.csv'))
        toast.success('CSV downloaded!')
      } else {
        const fd = new FormData()
        files.forEach(f => fd.append('files', f.file))
        const { data } = await axios.post(`${API}/export-csv-batch`, fd, { responseType: 'blob' })
        triggerDownload(new Blob([data]), 'invoices_batch.csv')
        toast.success('Batch CSV downloaded!')
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || 'CSV export failed')
    } finally {
      setLoading(false); setLoadingAction('')
    }
  }

  // ── sample helpers ────────────────────────────────────────────────────────
  const handleExtractSample = async (filename) => {
    setSampleLoading(true)
    try {
      const { data } = await axios.post(`${API}/extract-sample?filename=${encodeURIComponent(filename)}`)
      saveHistory([{ id: Date.now(), filename, data, date: new Date().toISOString(), hasPreview: true, isSample: true }])
      navigate('/result', { state: { result: data, filename, isSample: true } })
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Extraction failed')
    } finally {
      setSampleLoading(false)
    }
  }

  const handleExtractAllSamples = async () => {
    setSampleLoading(true)
    try {
      const { data } = await axios.post(`${API}/extract-all-samples`)
      const ok  = data.results.filter(r => r.status === 'success')
      const bad = data.results.filter(r => r.status === 'error')
      if (ok.length)  toast.success(`Extracted ${ok.length} sample invoice${ok.length > 1 ? 's' : ''}`)
      if (bad.length) toast.error(`${bad.length} failed`)
      saveHistory(ok.map(r => ({ id: Date.now() + Math.random(), filename: r.filename, data: r.data, date: new Date().toISOString(), hasPreview: true })))
      navigate('/history')
    } catch (err) {
      toast.error('Batch extraction failed')
    } finally {
      setSampleLoading(false)
    }
  }

  // ── render ────────────────────────────────────────────────────────────────
  const busy = loading || sampleLoading

  return (
    <div className={styles.page}>

      {/* ── Hero ── */}
      <div className={styles.hero}>
        <motion.div className={styles.badge}
          initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45 }}>
          <Zap size={11} /> OCR-Powered · FastAPI + React
        </motion.div>
        <motion.h1 className={styles.title}
          initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45, delay: 0.1 }}>
          Invoice Data<br /><span className={styles.gradient}>Extraction</span>
        </motion.h1>
        <motion.p className={styles.subtitle}
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.45, delay: 0.2 }}>
          Upload PDF or image invoices — extract, download as JSON or CSV instantly.
        </motion.p>
      </div>

      {/* ── Sample Invoices Panel ── */}
      {sampleInvoices.length > 0 && (
        <motion.div className={styles.samplePanel}
          initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.22 }}>
          <button className={styles.sampleToggle} onClick={() => setSamplesOpen(o => !o)}>
            <FolderOpen size={14} />
            <span>Sample Invoices ({sampleInvoices.length} bundled)</span>
            <ChevronDown size={13} style={{ transform: samplesOpen ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }} />
          </button>
          <AnimatePresence>
            {samplesOpen && (
              <motion.div className={styles.sampleBody}
                initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }}>
                <div className={styles.sampleHead}>
                  <span className={styles.sampleNote}>Click ▶ to extract individually, or run all at once</span>
                  <button className={styles.btnExtractAll} onClick={handleExtractAllSamples} disabled={busy}>
                    {sampleLoading ? <><Loader2 size={12} className={styles.spin} /> Processing…</> : <><Zap size={12} /> Extract All</>}
                  </button>
                </div>
                <div className={styles.sampleScroll}>
                  {sampleInvoices.map(({ filename, size_kb }) => (
                    <div key={filename} className={styles.sampleRow}>
                      <FileText size={13} className={styles.sampleIcon} />
                      <span className={styles.sampleName}>{filename}</span>
                      <span className={styles.sampleSize}>{size_kb} KB</span>
                      <button className={styles.samplePlay} onClick={() => handleExtractSample(filename)} disabled={busy} title="Extract">
                        <PlayCircle size={16} />
                      </button>
                    </div>
                  ))}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </motion.div>
      )}

      {/* ── Mode Toggle ── */}
      <motion.div className={styles.modeToggle}
        initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.28 }}>
        <button className={`${styles.modeBtn} ${mode === 'single' ? styles.modeActive : ''}`}
          onClick={() => { setMode('single'); setFiles([]) }}>
          <File size={13} /> Single Invoice
        </button>
        <button className={`${styles.modeBtn} ${mode === 'batch' ? styles.modeActive : ''}`}
          onClick={() => { setMode('batch'); setFiles([]) }}>
          <LayoutList size={13} /> Batch (up to 50)
        </button>
      </motion.div>

      {/* ── Drop Zone ── */}
      <motion.div className={styles.dropWrap}
        initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.33 }}>

        <div {...getRootProps()} className={`${styles.dropzone} ${isDragActive ? styles.dropActive : ''}`}>
          <input {...getInputProps()} />
          <div className={styles.dropInner}>
            <div className={styles.dropIcon}><FileUp size={30} strokeWidth={1.4} /></div>
            <p className={styles.dropMain}>{isDragActive ? 'Drop invoices here!' : 'Drag & drop invoices here'}</p>
            <p className={styles.dropSub}>
              Click to browse · PDF, PNG, JPG, TIFF
              {mode === 'batch' && <span className={styles.batchHint}> · up to 50 files</span>}
            </p>
          </div>
        </div>

        {/* ── File List ── */}
        <AnimatePresence>
          {files.length > 0 && (
            <motion.div className={styles.fileList}
              initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }}>

              <div className={styles.fileListHeader}>
                <span className={styles.fileCount}>{files.length} file{files.length > 1 ? 's' : ''} selected{mode === 'batch' ? ` / 50` : ''}</span>
                {files.length > 1 && (
                  <button className={styles.clearBtn} onClick={clearFiles}>Clear all</button>
                )}
              </div>

              <div className={styles.fileScroll}>
                {files.map(({ file, id }) => (
                  <motion.div key={id} layout
                    initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 10 }}
                    className={styles.fileRow}>
                    <FileText size={14} className={styles.fileIcon} />
                    <div className={styles.fileMeta}>
                      <span className={styles.fileName}>{file.name}</span>
                      <span className={styles.fileSize}>{(file.size / 1024).toFixed(1)} KB</span>
                    </div>
                    <button className={styles.fileRemove} onClick={() => removeFile(id)} title="Remove">
                      <X size={12} />
                    </button>
                  </motion.div>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>

      {/* ── Action Buttons ── */}
      <motion.div className={styles.actions}
        initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.4 }}>

        {/* Primary — Extract & View */}
        <button className={styles.btnPrimary} onClick={handleExtract} disabled={!files.length || busy}>
          {loading && loadingAction === 'extract'
            ? <><Loader2 size={15} className={styles.spin} /> Processing…</>
            : <><Zap size={15} />
                {mode === 'batch'
                  ? `Extract ${files.length || ''} Invoice${files.length !== 1 ? 's' : ''}`
                  : 'Extract & View'}
                <ChevronRight size={14} /></>}
        </button>

        {/* Download JSON */}
        <button className={styles.btnOutline} onClick={handleDownloadJSON} disabled={!files.length || busy} title="Download JSON">
          {loading && loadingAction === 'json'
            ? <><Loader2 size={14} className={styles.spin} /> Exporting…</>
            : <><FileJson size={14} /> Download JSON</>}
        </button>

        {/* Download CSV */}
        <button className={styles.btnOutline} onClick={handleDownloadCSV} disabled={!files.length || busy} title="Download CSV">
          {loading && loadingAction === 'csv'
            ? <><Loader2 size={14} className={styles.spin} /> Exporting…</>
            : <><Download size={14} /> Download CSV</>}
        </button>
      </motion.div>

      {/* ── Format Info ── */}
      {files.length > 0 && (
        <motion.p className={styles.formatNote}
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.1 }}>
          {mode === 'single'
            ? '"Extract & View" shows the result in browser · JSON & CSV buttons download the file directly'
            : `Batch mode: all ${files.length} invoices processed together · JSON & CSV contain all results in one file`}
        </motion.p>
      )}

      {/* ── Feature Cards ── */}
      <motion.div className={styles.features}
        initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.5 }}>
        {[
          { icon: '🔍', title: 'Tesseract OCR',     desc: 'Industry-grade optical character recognition' },
          { icon: '⚡', title: 'FastAPI Backend',   desc: 'High-performance async Python API' },
          { icon: '📋', title: 'JSON & CSV Export', desc: 'Structured output for every invoice field' },
          { icon: '🗂️', title: 'Batch up to 50',   desc: 'Process 50 invoices in a single request' },
        ].map(({ icon, title, desc }) => (
          <div key={title} className={styles.featureCard}>
            <span className={styles.featureEmoji}>{icon}</span>
            <h3 className={styles.featureTitle}>{title}</h3>
            <p className={styles.featureDesc}>{desc}</p>
          </div>
        ))}
      </motion.div>
    </div>
  )
}
