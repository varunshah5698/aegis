import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowUpRight, CheckCircle2, Receipt } from 'lucide-react'
import { api, ApiError } from '../lib/api'
import type { Order, Plan } from '../lib/types'
import { PageHeader } from '../components/ui'

/**
 * Pay and check out: pick a plan, confirm the demo checkout, and keep
 * receipts (orders) with amounts and timestamps.
 */
export default function Checkout() {
  const queryClient = useQueryClient()
  const [error, setError] = useState('')
  const [done, setDone] = useState<Order | null>(null)

  const { data: plans } = useQuery<Plan[]>({
    queryKey: ['plans'],
    queryFn: () => api.get<Plan[]>('/api/plans'),
    staleTime: 300_000,
  })

  const { data: orders } = useQuery<Order[]>({
    queryKey: ['orders'],
    queryFn: () => api.get<Order[]>('/api/orders'),
    staleTime: 15_000,
  })

  const checkout = useMutation<Order, ApiError, string>({
    mutationFn: (plan) => api.post<Order>('/api/checkout', { plan }),
    onSuccess: (order) => {
      setDone(order)
      setError('')
      void queryClient.invalidateQueries({ queryKey: ['orders'] })
      void queryClient.invalidateQueries({ queryKey: ['overview'] })
    },
    onError: (err) => {
      setDone(null)
      setError(err.message)
    },
  })

  return (
    <div className="mx-auto max-w-[1080px]">
      <PageHeader
        eyebrow="Commercial"
        title="Plans and checkout"
        description="Prices in USD. The checkout below records a demo order instantly — no real payment is processed. Connect a payment provider webhook before accepting live payments."
      />

      {done && (
        <div className="panel mb-5 flex items-start gap-3 border-teal/40 bg-teal/8 p-4.5">
          <CheckCircle2 size={20} className="mt-0.5 shrink-0 text-teal" aria-hidden />
          <div>
            <p className="text-[16px] font-medium">
              You are on {done.plan} — {done.amount ?? `$${(done.amount_cents / 100).toFixed(2)}`}
            </p>
            <p className="mt-1 text-[14px] text-ink-soft">
              Order {done.id.slice(0, 8)} · {done.status} · {done.note ?? 'Demo checkout — no real payment was processed.'}
            </p>
          </div>
        </div>
      )}
      {error && <p className="mt-6 text-[15px] font-medium text-danger">{error}</p>}

      <div className="grid gap-4 md:grid-cols-3">
        {(plans ?? []).map((p, i) => (
          <article key={p.key} className={`panel panel-hover flex flex-col p-5 ${i === 1 ? 'ring-2 ring-lime' : ''}`}>
            {i === 1 && (
              <span className="mb-3 inline-flex w-fit items-center gap-1 rounded-full bg-lime px-3 py-1 text-[12.5px] font-semibold text-ink">
                Most popular
              </span>
            )}
            <h2 className="text-[20px] font-medium">{p.name}</h2>
            <p className="mt-2">
              <span className="text-[40px] font-medium tracking-tight">{p.amount}</span>
            </p>
            <button
              type="button"
              className={`mt-5 inline-flex w-full items-center justify-center gap-2 rounded-[14px] px-6 py-3 text-[16px] font-medium transition ${
                i === 1 ? 'bg-ink text-paper hover:-translate-y-0.5' : 'border border-line hover:bg-mist'
              }`}
              disabled={checkout.isPending}
              onClick={() => checkout.mutate(p.key)}
            >
              {checkout.isPending ? 'Processing…' : `Choose ${p.name}`}
              <ArrowUpRight size={16} aria-hidden />
            </button>
          </article>
        ))}
      </div>

      <h2 className="mt-9 flex items-center gap-2.5 text-[18px] font-semibold">
        <Receipt size={19} aria-hidden />
        Receipts
      </h2>
      {!orders?.length ? (
        <p className="mt-3 text-[15px] text-ink-soft">No orders yet — your receipts appear here after checkout.</p>
      ) : (
        <div className="panel scroll-ink mt-4 overflow-x-auto">
          <table className="table-grid">
            <thead>
              <tr>
                <th>Order</th>
                <th>Plan</th>
                <th>Amount</th>
                <th>Status</th>
                <th>Date</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((o) => (
                <tr key={o.id}>
                  <td className="font-mono text-[13px]">{o.id.slice(0, 8)}</td>
                  <td className="font-medium capitalize">{o.plan}</td>
                  <td className="tabular-nums">${(o.amount_cents / 100).toFixed(2)}</td>
                  <td>{o.status}</td>
                  <td className="whitespace-nowrap text-ink-soft">
                    {o.created_at ? new Date(o.created_at).toLocaleString() : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
