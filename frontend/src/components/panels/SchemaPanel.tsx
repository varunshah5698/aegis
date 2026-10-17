import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Save, TriangleAlert } from 'lucide-react'
import { api, ApiError } from '../../lib/api'
import { AiSection } from '../AiPanel'
import type { ColumnProfile, Manifest } from '../../lib/types'

/**
 * Schema inspector + semantic mapping editor. Users can correct uncertain
 * mappings before rerunning analysis; overrides are persisted server-side and
 * merged into the next run (spec #5.2).
 */
const ROLES: [string, string][] = [
  ['none', '— leave as inferred —'],
  ['source_account', 'Source account'],
  ['destination_account', 'Destination account'],
  ['sender', 'Sender'],
  ['receiver', 'Receiver'],
  ['source_customer', 'Source customer'],
  ['destination_customer', 'Destination customer'],
  ['amount_source', 'Amount (source)'],
  ['amount_destination', 'Amount (destination)'],
  ['currency_source', 'Currency (source)'],
  ['currency_destination', 'Currency (destination)'],
  ['fx_rate', 'FX rate'],
  ['fee_amount', 'Fee amount'],
  ['transaction_time', 'Transaction time'],
  ['settlement_time', 'Settlement time'],
  ['status', 'Status'],
  ['category', 'Category'],
  ['country', 'Country'],
  ['institution', 'Institution'],
  ['payment_rail', 'Payment rail'],
  ['customer_id', 'Customer ID'],
  ['merchant_id', 'Merchant ID'],
  ['device', 'Device'],
  ['target', 'Target / label'],
  ['datetime', 'Date & time'],
  ['identifier', 'Identifier'],
  ['categorical', 'Categorical'],
  ['numeric', 'Numeric'],
  ['text', 'Free text'],
  ['geographic', 'Geographic'],
]

const STATE_TONE: Record<string, string> = {
  available: 'bg-lime',
  'available with limitations': 'bg-amber/30',
  needs_configuration: 'bg-amber/30',
  unavailable: 'bg-mist',
}

export default function SchemaPanel({ manifest, runId }: { manifest: Manifest; runId: string }) {
  const queryClient = useQueryClient()
  const [overrides, setOverrides] = useState<Record<string, string>>({})
  const [q, setQ] = useState('')

  const save = useMutation({
    mutationFn: (mapping: Record<string, string>) =>
      api.post(`/api/datasets/${manifest.dataset_id}/mapping`, { mapping }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['manifest', runId] })
      void queryClient.invalidateQueries({ queryKey: ['schema', manifest.dataset_id] })
    },
  })

  const columns = manifest.columns ?? []
  const shown = q
    ? columns.filter(
        (c) =>
          c.name.toLowerCase().includes(q.toLowerCase()) ||
          c.semantic_type.toLowerCase().includes(q.toLowerCase()),
      )
    : columns

  const caps = manifest.capabilities ?? {}
  const pendingCount = Object.keys(overrides).length

  return (
    <div className="space-y-6">
      <AiSection runId={runId} section="schema" />

      {/* -------------------------------------------------- capabilities */}
      <div className="panel p-5">
        <h2 className="text-[22px] font-medium">
          What this file <span className="marker">supports</span>
        </h2>
        <p className="mt-1 text-[14.5px] text-ink-soft">
          Every module declares a state with its reason — unavailable modules never show
          fabricated results.
        </p>
        <ul className="mt-5 grid gap-3 sm:grid-cols-2">
          {Object.entries(caps).map(([key, cap]) => (
            <li key={key} className="rounded-[14px] border border-line/30 px-4 py-3">
              <div className="flex items-center justify-between gap-3">
                <span className="text-[15px] font-medium capitalize">{key.replace(/_/g, ' ')}</span>
                <span className={`chip text-[12px] ${STATE_TONE[cap.state] ?? 'bg-mist'}`}>
                  {cap.state}
                </span>
              </div>
              <p className="mt-1.5 text-[13.5px] leading-relaxed text-ink-soft">{cap.reason}</p>
            </li>
          ))}
        </ul>
      </div>

      {/* ------------------------------------------------------- columns */}
      <div className="panel p-5">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2 className="text-[22px] font-medium">
              Column meanings <span className="marker">({columns.length})</span>
            </h2>
            <p className="mt-1 text-[14.5px] text-ink-soft">
              Correct an uncertain mapping, then rerun the analysis to activate dependent
              modules.
            </p>
          </div>
          <div className="flex gap-3">
            <input
              className="field max-w-[220px]"
              placeholder="Filter columns…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              aria-label="Filter columns"
            />
            <button
              type="button"
              className="btn px-4 py-2.5 text-[15px]"
              disabled={pendingCount === 0 || save.isPending}
              onClick={() => save.mutate(overrides)}
            >
              <Save size={15} aria-hidden />
              {save.isPending ? 'Saving…' : `Save ${pendingCount || ''} mapping${pendingCount === 1 ? '' : 's'}`}
            </button>
          </div>
        </div>

        {save.isSuccess && (
          <p className="mt-4 flex items-center gap-2 rounded-[14px] border border-teal bg-teal/10 px-4 py-3 text-[14.5px]">
            <CheckCircle2 size={16} className="text-teal" aria-hidden />
            Mapping saved. Rerun the analysis from the dataset page to rebuild dependent
            modules with these roles.
          </p>
        )}
        {save.error && (
          <p className="mt-4 rounded-[14px] border border-danger bg-danger/8 px-4 py-3 text-[14.5px] text-danger">
            {save.error instanceof ApiError ? save.error.message : 'Could not save mapping.'}
          </p>
        )}

        <div className="scroll-ink mt-5 overflow-x-auto">
          <table className="table-grid">
            <thead>
              <tr>
                <th>Column</th>
                <th>Type</th>
                <th>Inferred meaning</th>
                <th>Conf.</th>
                <th>Missing</th>
                <th>Unique</th>
                <th>Why</th>
                <th>Override</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((c) => (
                <tr key={c.name}>
                  <td className="font-medium whitespace-nowrap">
                    {c.name}
                    {c.is_identifier && (
                      <span className="ml-1.5 rounded bg-mist px-1.5 py-0.5 text-[10.5px]">id</span>
                    )}
                    {c.is_target && (
                      <span className="ml-1.5 rounded bg-lime px-1.5 py-0.5 text-[10.5px]">target</span>
                    )}
                    {c.is_sensitive && (
                      <span className="ml-1.5 rounded bg-amber/35 px-1.5 py-0.5 text-[10.5px]">sensitive</span>
                    )}
                  </td>
                  <td className="text-[13px] whitespace-nowrap">{c.physical_type}</td>
                  <td>
                    <span className="block text-[13.5px]">{c.likely_meaning}</span>
                    <span className="text-[11.5px] text-ink-soft">{c.semantic_type}</span>
                  </td>
                  <td>
                    <Confidence value={c.semantic_confidence} />
                  </td>
                  <td className="tabular-nums">{c.null_pct}%</td>
                  <td className="tabular-nums">{c.unique_count.toLocaleString()}</td>
                  <td className="max-w-[260px] text-[12.5px] text-ink-soft">{c.reason}</td>
                  <td>
                    <select
                      className="min-w-[170px] rounded-[10px] border border-line bg-paper px-2 py-1.5 text-[13px]"
                      value={overrides[c.name] ?? c.user_override ?? ''}
                      onChange={(e) =>
                        setOverrides((prev) => ({ ...prev, [c.name]: e.target.value }))
                      }
                      aria-label={`Semantic role for ${c.name}`}
                    >
                      {ROLES.map(([value, label]) => (
                        <option key={value} value={value}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {columns.length === 0 && (
          <p className="mt-4 text-[15px] text-ink-soft">No columns in the manifest.</p>
        )}
        {columns.some((c: ColumnProfile) => c.semantic_confidence < 0.7) && (
          <p className="mt-4 flex items-start gap-2 text-[14px] text-ink-soft">
            <TriangleAlert size={15} className="mt-0.5 shrink-0 text-amber" aria-hidden />
            {columns.filter((c: ColumnProfile) => c.semantic_confidence < 0.7).length} column(s)
            have confidence below 70% — reviewing those first usually unlocks more modules.
          </p>
        )}
      </div>
    </div>
  )
}

function Confidence({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  const tone = value >= 0.85 ? 'bg-teal' : value >= 0.7 ? 'bg-lime' : 'bg-amber'
  return (
    <span className="flex items-center gap-2" title={`${pct}% confidence`}>
      <span className="block h-2 w-12 overflow-hidden rounded-full border border-line/40 bg-mist">
        <span className={`block h-full ${tone}`} style={{ width: `${pct}%` }} />
      </span>
      <span className="tabular-nums text-[12.5px]">{pct}%</span>
    </span>
  )
}
