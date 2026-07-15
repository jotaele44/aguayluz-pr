import { useRef, useState } from 'react'
import { postAiQuery } from '@/lib/api'
import { Bot, Loader2, MessageCircle, Send, X } from 'lucide-react'

export default function AiQueryPanel() {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(false)
  const inputRef = useRef(null)

  const submit = async (e) => {
    e?.preventDefault()
    const q = query.trim()
    if (!q || loading) return
    setMessages((m) => [...m, { role: 'user', text: q }])
    setQuery('')
    setLoading(true)
    const result = await postAiQuery(q)
    setMessages((m) => [...m, { role: 'assistant', text: result?.answer ?? result?.error ?? 'No response.' }])
    setLoading(false)
    setTimeout(() => inputRef.current?.focus(), 50)
  }

  const handleKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-5 right-5 z-40 flex items-center gap-2 rounded-full border border-sky-700/60 bg-sky-950/90 px-4 py-2.5 text-sm text-sky-200 shadow-lg backdrop-blur hover:bg-sky-900/80 transition"
        title="Ask a question about the dashboard data"
      >
        <MessageCircle className="h-4 w-4" />
        Ask AI
      </button>

      {open && (
        <div className="fixed bottom-20 right-5 z-50 flex flex-col w-[360px] max-h-[520px] rounded-xl border border-slate-700/70 bg-slate-950/95 shadow-2xl backdrop-blur">
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-100">
              <Bot className="h-4 w-4 text-sky-400" />
              Ask about this data
            </div>
            <button onClick={() => setOpen(false)} className="text-slate-500 hover:text-slate-300 transition">
              <X className="h-4 w-4" />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto p-4 space-y-3 min-h-[180px]">
            {messages.length === 0 && (
              <div className="space-y-2">
                <p className="text-xs text-slate-500 text-center">Try asking:</p>
                {[
                  'How many assets are tracked?',
                  'What sectors have the most events?',
                  'Summarize the current infrastructure status',
                ].map((suggestion) => (
                  <button
                    key={suggestion}
                    onClick={() => { setQuery(suggestion); inputRef.current?.focus() }}
                    className="block w-full text-left rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2 text-xs text-slate-400 hover:text-slate-200 hover:border-slate-700 transition"
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[280px] rounded-xl px-3 py-2 text-sm leading-relaxed ${
                  m.role === 'user'
                    ? 'bg-sky-900/60 text-sky-100 rounded-br-sm'
                    : 'bg-slate-800 text-slate-200 rounded-bl-sm'
                }`}>
                  {m.text}
                </div>
              </div>
            ))}
            {loading && (
              <div className="flex justify-start">
                <div className="flex items-center gap-2 rounded-xl bg-slate-800 px-3 py-2 text-sm text-slate-400">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" /> Thinking…
                </div>
              </div>
            )}
          </div>

          <form onSubmit={submit} className="flex items-center gap-2 px-3 py-3 border-t border-slate-800">
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKey}
              placeholder="Ask about the data…"
              disabled={loading}
              className="flex-1 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:outline-none focus:border-sky-600 disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={!query.trim() || loading}
              className="rounded-lg bg-sky-700 p-2 text-white hover:bg-sky-600 disabled:opacity-40 transition"
            >
              <Send className="h-4 w-4" />
            </button>
          </form>
        </div>
      )}
    </>
  )
}
