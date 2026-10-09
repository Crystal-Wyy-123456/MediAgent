<script setup>
defineProps({
  label: String,
  value: [String, Number],
  foot: String,
  tone: { type: String, default: '' },
  small: Boolean,
})
</script>

<template>
  <div class="stat" :class="tone">
    <div class="stat-label">{{ label }}</div>
    <div class="stat-value" :class="{ small }">{{ value }}</div>
    <div v-if="foot" class="stat-foot">{{ foot }}</div>
  </div>
</template>
