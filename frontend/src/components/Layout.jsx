import { NavLink, useLocation } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { History, Home, Zap } from 'lucide-react'
import styles from './Layout.module.css'

const NAV = [
  { to: '/',        label: 'Extract', Icon: Home    },
  { to: '/history', label: 'History', Icon: History },
]

export default function Layout({ children }) {
  const { pathname } = useLocation()

  return (
    <div className={styles.root}>
      {/* Ambient background glow */}
      <div className={styles.ambient} />

      <header className={styles.header}>
        <NavLink to="/" className={styles.logo}>
          <Zap size={20} strokeWidth={2.5} />
          <span>InvoiceOCR</span>
        </NavLink>

        <nav className={styles.nav}>
          {NAV.map(({ to, label, Icon }) => (
            <NavLink
              key={to}
              to={to}
              end                              /* "end" prevents "/" matching every route */
              className={({ isActive }) =>
                `${styles.navLink} ${isActive ? styles.active : ''}`
              }
            >
              <Icon size={15} strokeWidth={2} />
              {label}
            </NavLink>
          ))}
        </nav>
      </header>

      <main className={styles.main}>
        <AnimatePresence mode="wait">
          <motion.div
            key={pathname}
            className={styles.pageWrapper}
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
          >
            {children}
          </motion.div>
        </AnimatePresence>
      </main>

      <footer className={styles.footer}>
        <span>Invoice OCR Extractor · FastAPI + React</span>
      </footer>
    </div>
  )
}
