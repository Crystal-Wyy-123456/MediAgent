<script setup>
import { computed } from 'vue'

const props = defineProps({
  spans: { type: Array, default: () => [] },
  totalMs: { type: Number, default: 0 },
})

const maxMs = computed(() => props.totalMs || Math.max(1, ...props.spans.map((s) => s.elapsed_ms || 0)))

const KIND_COLORS = {
  orchestration: '#1a6fd4',
  routing: '#6941c6',
  agent: '#0d9b8a',
  node: '#2f8bf0',
  tool: '#c77700',
  retrieval: '#0ea5e9',
  rerank: '#7c3aed',
  review: '#e07a1a',
  track: '#94a3b8',
  pipeline: '#0f766e',
  pipeline_step: '#14b8a6',
}

const KIND_LABELS = {
  orchestration: '统一调度',
  routing: '问题分流',
  agent: '业务模块处理',
  node: '环节处理',
  tool: '外部工具调用',
  retrieval: '知识检索',
  rerank: '结果排序',
  review: '病历评审',
  track: '校验轨道',
  pipeline: '诊疗联动',
  pipeline_step: '联动步骤',
}

function width(span) {
  return Math.max(2, ((span.elapsed_ms || 0) / maxMs.value) * 100)
}

function color(span) {
  return KIND_COLORS[span.kind] || '#64748b'
}
</script>

<template>
  <div v-if="spans.length" class="stack" style="gap: 7px">
    <div v-for="span in spans" :key="span.span_id" class="row" style="gap: 10px">
      <div
        class="nowrap"
        :style="{ width: '210px', paddingLeft: `${span.depth * 12}px`, fontSize: '11.5px', color: span.depth ? 'var(--ink-3)' : 'var(--ink-2)' }"
      >
        {{ KIND_LABELS[span.kind] || '处理环节' }}
      </div>
      <div style="flex: 1; min-width: 0; background: #f1f5f9; border-radius: 4px; height: 16px; position: relative; overflow: hidden">
        <div
          :style="{
            width: `${width(span)}%`,
            background: color(span),
            height: '100%',
            borderRadius: '4px',
            opacity: span.ok ? 0.9 : 1,
          }"
        ></div>
      </div>
      <div class="mono nowrap" style="width: 74px; text-align: right; font-size: 11.5px; color: var(--ink-3)">
        {{ (span.elapsed_ms || 0).toFixed(1) }}ms
      </div>
    </div>
  </div>
  <div v-else class="empty"><span class="icon">⏱</span>暂无环节数据</div>
</template>
