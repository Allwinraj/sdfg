import { useCallback, useEffect, useMemo } from 'react'
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  Position,
  useEdgesState,
  useNodesState,
  type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import Icon from './Icon'
import { useAgents } from '../context/AgentContext'
import {
  agentTitle,
  layoutPipeline,
  type FlowNode,
  type NodeConfig,
} from '../data/flowNodes'

function PipelineNodeView({ data }: NodeProps<FlowNode>) {
  const config = data as NodeConfig
  const isKnowledge = config.agent === 'ingestion' && config.mode === 'knowledge'
  const isOutput = config.agent === 'output'
  const ports = config.ports.length ? config.ports : ['default']
  const status = config.runStatus
  return (
    <div
      className={`min-w-[200px] rounded-xl border bg-surface-container-high p-4 transition-colors hover:border-tertiary-fixed-dim ${
        isOutput ? 'node-glow-gold border-primary-fixed-dim/30' : 'node-glow border-tertiary-fixed-dim/30'
      } ${isKnowledge ? 'border-dashed' : ''}`}
    >
      <Handle type="target" position={Position.Top} id="default" className="!bg-tertiary-fixed-dim" />
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded bg-surface border border-tertiary-fixed-dim/30">
          <Icon
            name={config.icon}
            className={isOutput ? 'text-primary-fixed-dim' : 'text-tertiary-fixed-dim'}
          />
        </div>
        <div className="min-w-0">
          <div className="truncate font-label-md text-on-surface">{config.label}</div>
          <div className="mt-1 font-mono-label text-on-surface-variant">
            {agentTitle(config.agent, config.mode)}
            {config.mode ? ` · ${config.mode}` : ''}
          </div>
        </div>
      </div>
      {status && (
        <div
          className={`mt-3 inline-flex rounded-full border px-2 py-0.5 font-mono-label ${
            status === 'ok'
              ? 'border-emerald-400/30 text-emerald-300'
              : status === 'error'
                ? 'border-red-400/30 text-red-300'
                : status === 'skipped'
                  ? 'border-white/10 text-on-surface-variant'
                  : 'border-primary-fixed-dim/40 text-primary-fixed-dim'
          }`}
        >
          {status}
        </div>
      )}
      {ports.map((port, index) => (
        <Handle
          key={port}
          type="source"
          position={Position.Bottom}
          id={port}
          className="!bg-tertiary-fixed-dim"
          style={{ left: `${((index + 1) / (ports.length + 1)) * 100}%` }}
          title={port}
        />
      ))}
    </div>
  )
}

const nodeTypes = { pipeline: PipelineNodeView }

export default function Canvas() {
  const { pipeline, selectNode, run } = useAgents()
  const laid = useMemo(() => {
    const statusByNode = new Map((run?.steps ?? []).map((s) => [s.node_id, s.status]))
    const { nodes, edges } = layoutPipeline(pipeline)
    return {
      nodes: nodes.map((n) => ({
        ...n,
        data: { ...n.data, runStatus: statusByNode.get(n.id) },
      })),
      edges,
    }
  }, [pipeline, run])

  const [nodes, setNodes, onNodesChange] = useNodesState(laid.nodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(laid.edges)

  useEffect(() => {
    setNodes(laid.nodes)
    setEdges(laid.edges)
  }, [laid, setEdges, setNodes])

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: { id: string }) => {
      selectNode(node.id)
    },
    [selectNode],
  )

  return (
    <div className="relative h-full w-full bg-grid-pattern bg-surface">
      {pipeline.nodes.length === 0 && (
        <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center">
          <p className="max-w-sm text-center font-body-md text-on-surface-variant">
            Canvas is empty. Describe your process and upload working data — nodes appear
            as Nexus learns enough to build them.
          </p>
        </div>
      )}
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        onNodeDoubleClick={onNodeClick}
        nodeTypes={nodeTypes}
        fitView
        proOptions={{ hideAttribution: true }}
        className="bg-transparent"
      >
        <Background variant={BackgroundVariant.Dots} gap={24} size={1} color="rgba(255,255,255,0.06)" />
        <Controls showInteractive={false} className="!border-white/10 !bg-surface-container" />
      </ReactFlow>
    </div>
  )
}
