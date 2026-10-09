<script setup>
import { state } from '../store'
</script>

<template>
  <div class="toast-host">
    <div v-for="t in state.toasts" :key="t.id" class="toast" :class="t.type">{{ t.message }}</div>
  </div>
</template>
