import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ShieldAlert } from 'lucide-react'
import { api, ApiError } from '../lib/api'
import { PageHeader } from '../components/ui'

type Tab = 'users' | 'datasets' | 'runs' | 'audit'

interface AdminUser {
  id: string;
  email: string;
  display_name: string;
  is_active: boolean;
  created_at: string | null;
}

interface AdminDataset {
  id: string;
  filename: string;
  user_id: string | null;
  rows: number;
  cols: number;
  status: string;
  deleted: boolean;
  created_at: string | null;
}

interface AdminRun {
  id: string;
  dataset_id: string;
  user_id: string | null;
  status: string;
  progress: number;
  created_at: string | null;
}

interface AuditRow {
  action: string;
  user_id: string | null;
  resource_type: string;
  resource_id: string;
  created_at: string | null;
}

/**
 * Admin area: manage customers, plans and workspaces from one console with
 * the audit trail behind it. Requires the account email in ADMIN_EMAILS —
 * everyone else gets the 403 notice below.
 */
export default function Admin() {
  const [tab, setTab] = useState<Tab>('users')

  const users = useQuery<AdminUser[], ApiError>({
    queryKey: ['admin-users'],
    queryFn: () => api.get<AdminUser[]>('/api/admin/users'),
    retry: false,
  })
  const datasets = useQuery<AdminDataset[], ApiError>({
    queryKey: ['admin-datasets'],
    queryFn: () => api.get<AdminDataset[]>('/api/admin/datasets'),
    retry: false,
    enabled: tab === 'datasets',
  })
  const runs = useQuery<AdminRun[], ApiError>({
    queryKey: ['admin-runs'],
    queryFn: () => api.get<AdminRun[]>('/api/admin/runs'),
    retry: false,
    enabled: tab === 'runs',
  })
  const audit = useQuery<AuditRow[], ApiError>({
    queryKey: ['admin-audit'],
    queryFn: () => api.get<AuditRow[]>('/api/admin/audit'),
    retry: false,
    enabled: tab === 'audit',
  })

  if (users.error instanceof ApiError && users.error.status === 403) {
    return (
      <div className="mx-auto max-w-[720px] py-24 text-center">
        <ShieldAlert size={34} className="mx-auto text-amber" aria-hidden />
        <h1 className="mt-4 text-[30px] font-medium">Admin access only</h1>
        <p className="mt-2 text-ink-soft">
          This console is restricted to administrator emails (configured with
          ADMIN_EMAILS on the server). Your account is signed in but not listed.
        </p>
      </div>
    )
  }

  return (
    <>
      <PageHeader
        eyebrow="Administration"
        title="Admin console"
        description="Customers, datasets, analysis runs and the audit trail — everything in one place. Access is limited to administrator emails."
      />

      <div className="panel mb-5 flex flex-wrap gap-1.5 p-2">
        {(['users', 'datasets', 'runs', 'audit'] as Tab[]).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            aria-current={tab === t ? 'page' : undefined}
            className={`rounded-[11px] px-4 py-2 text-[14px] font-medium capitalize transition ${
              tab === t ? 'bg-ink text-paper' : 'text-ink-soft hover:bg-mist hover:text-ink'
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      <div className="panel scroll-ink overflow-x-auto">
        {tab === 'users' && <UsersTable query={users} />}
        {tab === 'datasets' && <DatasetsTable query={datasets} />}
        {tab === 'runs' && <RunsTable query={runs} />}
        {tab === 'audit' && <AuditTable query={audit} />}
      </div>
    </>
  )
}

function Loading({ what }: { what: string }) {
  return <p className="p-6 text-[15px] text-ink-soft">Loading {what}…</p>
}

function UsersTable({ query }: { query: ReturnType<typeof useQuery<AdminUser[], ApiError>> }) {
  const { data, isPending, error } = query
  if (isPending) return <Loading what="customers" />
  if (error) return <p className="p-6 text-danger">{error.message}</p>
  return (
    <table className="table-grid">
      <thead>
        <tr>
          <th>Email</th>
          <th>Display name</th>
          <th>Active</th>
          <th>Joined</th>
        </tr>
      </thead>
      <tbody>
        {(data ?? []).map((u) => (
          <tr key={u.id}>
            <td className="font-medium">{u.email}</td>
            <td>{u.display_name}</td>
            <td>{u.is_active ? 'yes' : 'no'}</td>
            <td className="whitespace-nowrap text-ink-soft">
              {u.created_at ? new Date(u.created_at).toLocaleString() : '—'}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function DatasetsTable({ query }: { query: ReturnType<typeof useQuery<AdminDataset[], ApiError>> }) {
  const { data, isPending, error } = query
  if (isPending) return <Loading what="datasets" />
  if (error) return <p className="p-6 text-danger">{error.message}</p>
  return (
    <table className="table-grid">
      <thead>
        <tr>
          <th>File</th>
          <th>Owner</th>
          <th>Rows</th>
          <th>Status</th>
          <th>Deleted</th>
        </tr>
      </thead>
      <tbody>
        {(data ?? []).map((d) => (
          <tr key={d.id}>
            <td className="font-medium break-all">{d.filename}</td>
            <td className="font-mono text-[12.5px]">{d.user_id?.slice(0, 8) ?? 'guest'}</td>
            <td className="tabular-nums">{d.rows.toLocaleString()}</td>
            <td>{d.status}</td>
            <td>{d.deleted ? 'yes' : 'no'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function RunsTable({ query }: { query: ReturnType<typeof useQuery<AdminRun[], ApiError>> }) {
  const { data, isPending, error } = query
  if (isPending) return <Loading what="runs" />
  if (error) return <p className="p-6 text-danger">{error.message}</p>
  return (
    <table className="table-grid">
      <thead>
        <tr>
          <th>Run</th>
          <th>Status</th>
          <th>Progress</th>
          <th>Started</th>
        </tr>
      </thead>
      <tbody>
        {(data ?? []).map((r) => (
          <tr key={r.id}>
            <td className="font-mono text-[12.5px]">{r.id.slice(0, 12)}</td>
            <td>{r.status}</td>
            <td className="tabular-nums">{r.progress}%</td>
            <td className="whitespace-nowrap text-ink-soft">
              {r.created_at ? new Date(r.created_at).toLocaleString() : '—'}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function AuditTable({ query }: { query: ReturnType<typeof useQuery<AuditRow[], ApiError>> }) {
  const { data, isPending, error } = query
  if (isPending) return <Loading what="audit events" />
  if (error) return <p className="p-6 text-danger">{error.message}</p>
  return (
    <table className="table-grid">
      <thead>
        <tr>
          <th>Action</th>
          <th>Resource</th>
          <th>When</th>
        </tr>
      </thead>
      <tbody>
        {(data ?? []).map((a, i) => (
          <tr key={i}>
            <td className="font-mono text-[12.5px]">{a.action}</td>
            <td className="text-ink-soft">{a.resource_type} {a.resource_id?.slice(0, 8)}</td>
            <td className="whitespace-nowrap text-ink-soft">
              {a.created_at ? new Date(a.created_at).toLocaleString() : '—'}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
