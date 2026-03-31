import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useDropzone } from 'react-dropzone'
import { motion, AnimatePresence } from 'framer-motion'
import { toast } from 'react-hot-toast'
import { Upload, FileText, X, Zap, Loader2, ChevronRight, FileUp } from 'lucide-react'
import axios from 'axios'
import styles from './Home.module.css'

const API = 'http://localhost:8000'

export default function Home() {
  const navigate = useNavigate()
  const [files, setFiles] = useState([])
  const [loading, setLoading] = useState(false)
  const [mode, setMode] = useState('single') // 'single' | 'batch'

  const onDrop = useCallback((accepted) => {
    const newFiles = accepted.map(f => ({ file: f, id: Math.random().toString(36).slice(2) }))
    if (mode === 'single') {
      setFiles(newFiles.slice(0, 1))
    } else {
      setFiles(prev => [...prev, ...newFiles].slice(0, 10))
    }
  }, [mode])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'application/pdf': ['.pdf'], 'image/*': ['.png', '.jpg', '.jpeg', '.tiff'] },
    maxFiles: mode === 'single' ? 1 : 10,
  })

  const removeFile = (id) => setFiles(prev => prev.filter(f => f.id !== id))

  const handleExtract = async () => {
    if (!files.length) { toast.error('Please upload at least one invoice'); return }
    setLoading(true)
    try {
      if (mode === 'single') {
        const fd = new FormData()
        fd.append('file', files[0].file)
        const { data } = await axios.post(`${API}/extract`, fd)
        // Save to localStorage history
        const history = JSON.parse(localStorage.getItem('invoice_history') || '[]')
        history.unshift({ id: Date.now(), filename: files[0].file.name, data, date: new Date().toISOString() })
        localStorage.setItem('invoice_history', JSON.stringify(history.slice(0, 20)))
        navigate('/result', {
  state: {
    result: data,
    filename: files[0].file.name,
    fileObject: files[0].file,   // ← add this
  }
})
      } else {
        const fd = new FormData()
        files.forEach(f => fd.append('files', f.file))
        const { data } = await axios.post(`${API}/extract-multiple`, fd)
        toast.success(`Extracted ${data.total} invoices`)
        const history = JSON.parse(localStorage.getItem('invoice_history') || '[]')
        data.results.forEach(r => {
          if (r.status === 'success') {
            history.unshift({ id: Date.now() + Math.random(), filename: r.filename, data: r.data, date: new Date().toISOString() })
          }
        })
        localStorage.setItem('invoice_history', JSON.stringify(history.slice(0, 20)))
        navigate('/history')
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Extraction failed. Is the backend running?')
    } finally {
      setLoading(false)
    }
  }

  const handleExportCSV = async () => {
    if (!files.length) return
    setLoading(true)
    try {
      const fd = new FormData()
      fd.append('file', files[0].file)
      const { data } = await axios.post(`${API}/export-csv`, fd, { responseType: 'blob' })
      const url = URL.createObjectURL(new Blob([data]))
      const a = document.createElement('a')
      a.href = url
      a.download = files[0].file.name.replace(/\.\w+$/, '.csv')
      a.click()
      toast.success('CSV downloaded!')
    } catch (err) {
      toast.error('CSV export failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className={styles.page}>
      {/* Hero */}
      <div className={styles.hero}>
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className={styles.badge}
        >
          <Zap size={11} /> OCR-Powered · FastAPI + React
        </motion.div>
        <motion.h1
          className={styles.title}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.1 }}
        >
          Invoice Data<br /><span className={styles.gradient}>Extraction</span>
        </motion.h1>
        <motion.p
          className={styles.subtitle}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.5, delay: 0.2 }}
        >
          Upload PDF or image invoices. Extract structured data instantly using OCR.
        </motion.p>
      </div>

      {/* Mode toggle */}
      <motion.div
        className={styles.modeToggle}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.3 }}
      >
        <button
          className={`${styles.modeBtn} ${mode === 'single' ? styles.modeActive : ''}`}
          onClick={() => { setMode('single'); setFiles([]) }}
        >Single Invoice</button>
        <button
          className={`${styles.modeBtn} ${mode === 'batch' ? styles.modeActive : ''}`}
          onClick={() => { setMode('batch'); setFiles([]) }}
        >Batch (up to 10)</button>
      </motion.div>

      {/* Drop zone */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.35 }}
        className={styles.dropContainer}
      >
        <div
          {...getRootProps()}
          className={`${styles.dropzone} ${isDragActive ? styles.dropActive : ''}`}
        >
          <input {...getInputProps()} />
          <div className={styles.dropInner}>
            <div className={styles.dropIcon}>
              <FileUp size={28} strokeWidth={1.5} />
            </div>
            <p className={styles.dropMain}>
              {isDragActive ? 'Drop it here!' : 'Drag & drop invoices here'}
            </p>
            <p className={styles.dropSub}>or click to browse · PDF, PNG, JPG, TIFF</p>
          </div>
        </div>

        {/* File list */}
        <AnimatePresence>
          {files.length > 0 && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className={styles.fileList}
            >
              {files.map(({ file, id }) => (
                <motion.div
                  key={id}
                  layout
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: 10 }}
                  className={styles.fileItem}
                >
                  <FileText size={16} className={styles.fileIcon} />
                  <div className={styles.fileMeta}>
                    <span className={styles.fileName}>{file.name}</span>
                    <span className={styles.fileSize}>{(file.size / 1024).toFixed(1)} KB</span>
                  </div>
                  <button className={styles.fileRemove} onClick={() => removeFile(id)}>
                    <X size={13} />
                  </button>
                </motion.div>
              ))}
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>

      {/* Actions */}
      <motion.div
        className={styles.actions}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.4 }}
      >
        <button
          className={styles.btnPrimary}
          onClick={handleExtract}
          disabled={!files.length || loading}
        >
          {loading ? (
            <><Loader2 size={16} className={styles.spin} /> Processing…</>
          ) : (
            <><Zap size={16} /> Extract Data <ChevronRight size={15} /></>
          )}
        </button>
        {mode === 'single' && files.length > 0 && (
          <button className={styles.btnSecondary} onClick={handleExportCSV} disabled={loading}>
            Export CSV
          </button>
        )}
      </motion.div>

      {/* Feature cards */}
      <motion.div
        className={styles.features}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.5 }}
      >
        {[
          { icon: '🔍', title: 'Tesseract OCR', desc: 'Industry-grade optical character recognition' },
          { icon: '⚡', title: 'FastAPI Backend', desc: 'High-performance async Python API' },
          { icon: '📋', title: 'Structured Output', desc: 'Clean JSON & CSV with all invoice fields' },
          { icon: '🧠', title: 'Smart Parsing', desc: 'Regex-based field extraction for GTA invoices' },
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
