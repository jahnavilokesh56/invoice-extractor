import axios from 'axios'

const API_BASE = 'http://localhost:8000'

export const api = {
  extract: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return axios.post(`${API_BASE}/extract`, fd)
  },

  extractMultiple: (files) => {
    const fd = new FormData()
    files.forEach(f => fd.append('files', f))
    return axios.post(`${API_BASE}/extract-multiple`, fd)
  },

  exportCSV: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return axios.post(`${API_BASE}/export-csv`, fd, { responseType: 'blob' })
  },
}
