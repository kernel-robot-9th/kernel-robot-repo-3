<script setup lang="ts">
withDefaults(defineProps<{ name: string; size?: number }>(), { size: 20 })
const paths: Record<string, string> = {
  grid: 'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
  orders: 'M8 4H5v17h14V4h-3 M9 2h6v4H9z M8 11h8 M8 15h5',
  arm: 'M3 21h18 M7 21v-5l5-4 M12 12l-5-5 4-4 7 7-3 5 M17 11l4 1-1 5-4-1 M5 5l3-3',
  robot: 'M5 8h14v11H5z M9 12h.01 M15 12h.01 M9 16h6 M12 8V4 M10 3h4 M2 12v4 M22 12v4 M8 19v2 M16 19v2',
  camera: 'M3 7h4l2-3h6l2 3h4v13H3z M16 13a4 4 0 1 1-8 0 4 4 0 0 1 8 0',
  package: 'M3 7l9-5 9 5v10l-9 5-9-5z M3 7l9 5 9-5 M12 12v10 M7 4l10 6',
  tools: 'M14 6a5 5 0 0 0-6 6L2 18l4 4 6-6a5 5 0 0 0 6-6l-4 2-3-3z',
  history: 'M3 11a9 9 0 1 1 2 7 M3 4v7h7 M12 7v6l4 2',
  menu: 'M3 6h18 M3 12h18 M3 18h18',
  arrow: 'M5 12h14 M14 7l5 5-5 5',
  check: 'M5 12l4 4L19 6',
  clock: 'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0 M12 7v6l4 2',
  alert: 'M12 3L2 21h20z M12 9v5 M12 18h.01',
  cart: 'M2 3h3l3 13h11l3-9H6 M10 21h.01 M18 21h.01',
  logout: 'M10 3H3v18h7 M9 12h13 M17 7l5 5-5 5',
  leaf: 'M20 3c-9-1-17 3-16 10 1 8 16 8 16-10 M5 20L16 9',
  milk: 'M8 2h8v4l3 4v12H5V10l3-4z M5 10h14 M8 6h8 M9 14h6v4H9z',
  snack: 'M5 2h14l-1 5 2 10-1 5H5l-1-5L6 7z M5 5h14 M5 19h14 M9 10h6v6H9z',
  bowl: 'M3 11h18c-1 7-4 10-9 10S4 18 3 11z M2 8h20 M8 5V2 M13 5V2 M18 5V2',
}
</script>

<template>
  <svg :width="size" :height="size" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" class="ui-icon"><path :d="paths[name] || paths.package" /></svg>
</template>
