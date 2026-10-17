import NetworkGraph from '../NetworkGraph'
import { AiSection } from '../AiPanel'
import type { Manifest } from '../../lib/types'

export default function NetworkPanel({
  runId,
  manifest,
}: {
  runId: string
  manifest: Manifest
}) {
  const cap = manifest.capabilities?.transfer_network
  if (cap && cap.state === 'unavailable') {
    return (
      <div className="panel p-5">
        <p className="font-medium">Transfer network unavailable</p>
        <p className="mt-1 text-[15px] text-ink-soft">{cap.reason}</p>
        <p className="mt-3 text-[14px] text-ink-soft">
          Open the <b>Schema</b> module to map source and destination account columns manually,
          then rerun the analysis.
        </p>
      </div>
    )
  }
  return (
    <div className="space-y-6">
      <AiSection runId={runId} section="network" />
      <NetworkGraph runId={runId} />
    </div>
  )
}
