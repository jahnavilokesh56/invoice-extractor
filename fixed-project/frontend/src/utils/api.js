import axios from 'axios'

// Use relative URLs so Vite proxy handles them (avoids CORS issues)
export const api = {
  extract: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return axios.post('/extract', fd)
  },

  extractMultiple: (files) => {
    const fd = new FormData()
    files.forEach(f => fd.append('files', f))
    return axios.post('/extract-multiple', fd)
  },

  exportCSV: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return axios.post('/export-csv', fd, { responseType: 'blob' })
  },
}
