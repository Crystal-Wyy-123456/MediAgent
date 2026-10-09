// 统一的 API 客户端：JSON 请求 + SSE 流式解析 + 错误归一化
const API_BASE = import.meta.env.VITE_API_BASE || ''

export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.status = status
  }
}

function authHeaders(token) {
  const headers = { 'Content-Type': 'application/json' }
  if (token) headers.Authorization = `Bearer ${token}`
  return headers
}

async function parse(response) {
  const text = await response.text()
  let data = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = text
  }
  if (!response.ok) {
    const detail = data && data.detail ? data.detail : `请求失败（HTTP ${response.status}）`
    throw new ApiError(typeof detail === 'string' ? detail : JSON.stringify(detail), response.status)
  }
  return data
}

export async function api(path, { method = 'GET', body, token } = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers: authHeaders(token),
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  return parse(response)
}

export async function upload(path, file, token) {
  const form = new FormData()
  form.append('file', file)
  const headers = token ? { Authorization: `Bearer ${token}` } : {}
  const response = await fetch(`${API_BASE}${path}`, { method: 'POST', headers, body: form })
  return parse(response)
}

/**
 * 消费后端的 SSE 事件流（POST + ReadableStream）。
 * onEvent({ event, data }) 会在每个事件到达时被调用。
 */
export async function stream(path, body, token, onEvent, signal) {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify(body),
    signal,
  })
  if (!response.ok || !response.body) {
    throw new ApiError(`流式请求失败（HTTP ${response.status}）`, response.status)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const blocks = buffer.split('\n\n')
    buffer = blocks.pop() || ''
    for (const block of blocks) {
      let event = 'message'
      const dataLines = []
      for (const line of block.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
      }
      if (!dataLines.length) continue
      let data = null
      try {
        data = JSON.parse(dataLines.join('\n'))
      } catch {
        data = dataLines.join('\n')
      }
      onEvent({ event, data })
    }
  }
}
