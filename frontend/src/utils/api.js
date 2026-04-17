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

  exportCSVBatch: (files) => {
    const fd = new FormData()
    files.forEach(f => fd.append('files', f))
    return axios.post(`${API_BASE}/export-csv-batch`, fd, { responseType: 'blob' })
  },

  exportJSONBatch: (files) => {
    const fd = new FormData()
    files.forEach(f => fd.append('files', f))
    return axios.post(`${API_BASE}/export-json-batch`, fd, { responseType: 'blob' })
  },

  listSampleInvoices: () => axios.get(`${API_BASE}/sample-invoices`),

  extractSample: (filename) =>
    axios.post(`${API_BASE}/extract-sample?filename=${encodeURIComponent(filename)}`),

  extractAllSamples: () => axios.post(`${API_BASE}/extract-all-samples`),
}
