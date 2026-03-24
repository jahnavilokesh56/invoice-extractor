import { Link, useLocation } from 'react-router-dom'
import { motion } from 'framer-motion'
import { FileText, History, Home, Zap } from 'lucide-react'
import styles from './Layout.module.css'

const NAV = [
  { to: '/',        label: 'Extract',  Icon: Home },
  { to: '/history', label: 'History',  Icon: History },
]

export default function Layout({ children }) {
  const { pathname } = useLocation()

  return (
    <div className={styles.root}>
      {/* Ambient bg */}
      <div className={styles.ambient} />

      <header className={styles.header}>
        <Link to="/" className={styles.logo}>
          <Zap size={20} strokeWidth={2.5} />
          <span>InvoiceOCR</span>
        </Link>
        <nav className={styles.nav}>
          {NAV.map(({ to, label, Icon }) => (
            <Link
              key={to}
              to={to}
              className={`${styles.navLink} ${pathname === to ? styles.active : ''}`}
            >
              <Icon size={15} strokeWidth={2} />
              {label}
            </Link>
          ))}
        </nav>
      </header>

      <main className={styles.main}>
        <motion.div
          key={pathname}
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
        >
          {children}
        </motion.div>
      </main>

      <footer className={styles.footer}>
        <span>Invoice OCR Extractor · FastAPI + React</span>
      </footer>
    </div>
  )
}
