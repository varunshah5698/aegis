import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { api, ApiError } from '../lib/api'
import type { Booking } from '../lib/types'
import { PageHeader } from '../components/ui'

/**
 * Book or schedule a review: pick a date and time, add a topic, manage
 * upcoming bookings and cancel when plans change.
 */
export default function Booking() {
  const queryClient = useQueryClient()
  const [topic, setTopic] = useState('')
  const [detail, setDetail] = useState('')
  const [when, setWhen] = useState('')
  const [formError, setFormError] = useState('')

  const { data: bookings, isPending } = useQuery<Booking[]>({
    queryKey: ['bookings'],
    queryFn: () => api.get<Booking[]>('/api/bookings'),
    staleTime: 15_000,
  })

  const create = useMutation<Booking, ApiError, { topic: string; detail: string; scheduled_at: string }>({
    mutationFn: (body) => api.post<Booking>('/api/bookings', body),
    onSuccess: () => {
      setTopic('')
      setDetail('')
      setWhen('')
      setFormError('')
      void queryClient.invalidateQueries({ queryKey: ['bookings'] })
      void queryClient.invalidateQueries({ queryKey: ['overview'] })
    },
    onError: (err) => setFormError(err.message),
  })

  const cancel = useMutation({
    mutationFn: (id: string) => api.post<Booking>(`/api/bookings/${id}/cancel`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['bookings'] })
      void queryClient.invalidateQueries({ queryKey: ['overview'] })
    },
  })

  const upcoming = (bookings ?? []).filter((b) => b.status === 'upcoming')
  const past = (bookings ?? []).filter((b) => b.status !== 'upcoming')

  return (
    <div className="mx-auto max-w-[980px]">
      <PageHeader
        eyebrow="Commercial"
        title="Book a review"
        description="Reserve time with an analyst to walk through a finding. Choose a slot, and the confirmation appears right here in your workspace."
      />

      <form
        className="panel space-y-4 p-5 sm:p-6"
        onSubmit={(e) => {
          e.preventDefault()
          setFormError('')
          if (!topic.trim() || !when) {
            setFormError('Add a topic and pick a date and time.')
            return
          }
          const iso = new Date(when).toISOString()
          create.mutate({ topic: topic.trim(), detail: detail.trim(), scheduled_at: iso })
        }}
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block">
            <span className="mb-1.5 block text-[14px] font-medium">Topic</span>
            <input
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              placeholder="e.g. Walk through flagged pass-through flows"
              maxLength={160}
              className="field"
            />
          </label>
          <label className="block">
            <span className="mb-1.5 block text-[14px] font-medium">Date and time</span>
            <input
              type="datetime-local"
              value={when}
              onChange={(e) => setWhen(e.target.value)}
              className="field"
            />
          </label>
        </div>
        <label className="block">
          <span className="mb-1.5 block text-[14px] font-medium">What should the analyst prepare? (optional)</span>
          <textarea
            value={detail}
            onChange={(e) => setDetail(e.target.value)}
            placeholder="Dataset name, finding, or question to focus on…"
            maxLength={600}
            rows={3}
            className="field"
          />
        </label>
        {formError && <p className="text-[14px] text-danger">{formError}</p>}
        <button type="submit" className="btn" disabled={create.isPending}>
          {create.isPending ? 'Booking…' : 'Confirm booking'}
        </button>
      </form>

      <h2 className="mt-8 text-[18px] font-semibold">Upcoming ({upcoming.length})</h2>
      {isPending ? (
        <p className="mt-3 text-ink-soft">Loading bookings…</p>
      ) : !upcoming.length ? (
        <p className="mt-3 text-[15px] text-ink-soft">Nothing scheduled — your confirmed reviews appear here.</p>
      ) : (
        <ul className="mt-4 space-y-2.5">
          {upcoming.map((b) => (
            <li key={b.id} className="panel panel-hover flex flex-wrap items-center gap-3 p-4.5">
              <div className="min-w-0 flex-1">
                <p className="text-[16.5px] font-medium">{b.topic}</p>
                <p className="text-[14px] text-ink-soft">
                  {b.scheduled_at ? new Date(b.scheduled_at).toLocaleString() : 'Unscheduled'}
                  {b.detail ? ` · ${b.detail}` : ''}
                </p>
              </div>
              <button
                type="button"
                onClick={() => cancel.mutate(b.id)}
                disabled={cancel.isPending}
                className="inline-flex items-center gap-1.5 rounded-[12px] border border-line/30 px-3.5 py-1.5 text-[13.5px] font-medium hover:bg-mist"
              >
                <X size={14} aria-hidden />
                Cancel
              </button>
            </li>
          ))}
        </ul>
      )}

      {past.length > 0 && (
        <>
          <h2 className="mt-8 text-[18px] font-semibold">Past and cancelled</h2>
          <ul className="mt-4 space-y-2 text-[14.5px] text-ink-soft">
            {past.map((b) => (
              <li key={b.id} className="rounded-[12px] border border-line/25 bg-mist px-4 py-2.5">
                <b className="text-ink">{b.topic}</b> · {b.status} ·{' '}
                {b.scheduled_at ? new Date(b.scheduled_at).toLocaleString() : 'unscheduled'}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
