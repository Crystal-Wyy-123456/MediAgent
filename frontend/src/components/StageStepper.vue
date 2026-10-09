<script setup>
import { computed } from 'vue'

const props = defineProps({
  stages: { type: Array, default: () => [] },
  current: { type: String, default: '' },
  handover: Boolean,
})

const order = computed(() => props.stages.map((s) => s.id))
const currentIndex = computed(() => {
  if (props.handover) return order.value.length
  return order.value.indexOf(props.current)
})

function stateOf(id) {
  const index = order.value.indexOf(id)
  if (props.handover) return index <= currentIndex.value ? 'done' : 'todo'
  if (index < currentIndex.value) return 'done'
  if (index === currentIndex.value) return 'active'
  return 'todo'
}
</script>

<template>
  <div class="row wrap" style="gap: 6px">
    <template v-for="(stage, i) in stages" :key="stage.id">
      <div
        class="chip"
        :style="{
          borderStyle: 'solid',
          cursor: 'default',
          background: stateOf(stage.id) === 'done' ? 'var(--ok-soft)' : stateOf(stage.id) === 'active' ? 'var(--brand-soft)' : 'var(--surface-2)',
          borderColor: stateOf(stage.id) === 'done' ? '#c7e9dc' : stateOf(stage.id) === 'active' ? 'var(--brand)' : 'var(--line-strong)',
          color: stateOf(stage.id) === 'done' ? 'var(--ok)' : stateOf(stage.id) === 'active' ? 'var(--brand-dark)' : 'var(--ink-3)',
          fontWeight: stateOf(stage.id) === 'active' ? 700 : 500,
        }"
      >
        <b style="font-family: var(--mono)">{{ i + 1 }}</b> {{ stage.label }}
        <span v-if="stateOf(stage.id) === 'done'">✓</span>
      </div>
      <span v-if="i < stages.length - 1" class="muted tiny">›</span>
    </template>
    <div v-if="handover" class="chip" style="border-style: solid; border-color: #f7cfcb; background: var(--danger-soft); color: var(--danger); font-weight: 700">
      🚑 医生接管
    </div>
  </div>
</template>
