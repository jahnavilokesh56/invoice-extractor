import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { FileText, Trash2, Eye, Clock, ChevronRight } from 'lucide-react'
import { toast } from 'react-hot-toast'
import styles from './History.module.css'

export default function History() {
  const navigate = useNavigate()
  const [history, setHistory] = useState([])

  useEffect(() => {
    const saved = JSON.parse(localStorage.getItem('invoice_history') || '[]')
    setHistory(saved)
  }, [])

  const clearAll = () => {
    localStorage.removeItem('invoice_history')
    setHistory([])
    toast.success('History cleared')
  }

  const removeItem = (id) => {
    const updated = history.filter(h => h.id !== id)
    localStorage.setItem('invoice_history', JSON.stringify(updated))
    setHistory(updated)
  }

  const viewResult = (item) => {
    navigate('/result', { state: { result: item.data, filename: item.filename } })
  }

  const formatDate = (iso) => {
    const d = new Date(iso)
    return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
      + ' · ' + d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })
  }

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>History</h1>
          <p className={styles.sub}>{history.length} extraction{history.length !== 1 ? 's' : ''} stored locally</p>
        </div>
        {history.length > 0 && (
          <button className={styles.clearBtn} onClick={clearAll}>
            <Trash2 size={14} /> Clear All
          </button>
        )}
      </div>

      {history.length === 0 ? (
        <motion.div
          className={styles.empty}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
        >
          <Clock size={40} strokeWidth={1} />
          <p>No extractions yet.</p>
          <button className={styles.goBtn} onClick={() => navigate('/')}>Extract an invoice</button>
        </motion.div>
      ) : (
        <div className={styles.list}>
          <AnimatePresence>
            {history.map((item, i) => (
              <motion.div
                key={item.id}
                layout
                initial={{ opacity: 0, x: -16 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 16 }}
                transition={{ delay: i * 0.04 }}
                className={styles.card}
              >
                <div className={styles.cardIcon}>
                  <FileText size={18} strokeWidth={1.5} />
                </div>
                <div className={styles.cardBody}>
                  <div className={styles.cardName}>{item.filename}</div>
                  <div className={styles.cardMeta}>
                    <span>{formatDate(item.date)}</span>
                    {item.data?.invoice_number && (
                      <span className={styles.invNo}>#{item.data.invoice_number}</span>
                    )}
                    {item.data?.grand_total && (
                      <span className={styles.amount}>
                        ₹{Number(item.data.grand_total).toLocaleString('en-IN')}
                      </span>
                    )}
                  </div>
                </div>
                <div className={styles.cardActions}>
                  <button className={styles.viewBtn} onClick={() => viewResult(item)}>
                    <Eye size={14} /> View <ChevronRight size={13} />
                  </button>
                  <button className={styles.deleteBtn} onClick={() => removeItem(item.id)}>
                    <Trash2 size={13} />
                  </button>
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      )}
    </div>
  )
}
