<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from './api'
import VideoTile from './VideoTile.vue'
const props = defineProps<{ token: string }>()
const feeds = ref<{ id: string; label: string; owner: string; transport: string; whep_url?: string }[]>([])
const error = ref('')
onMounted(async () => { try { feeds.value = (await api<{ items: typeof feeds.value }>('/admin/video', props.token)).items } catch (e) { error.value = String(e) } })
</script>
<template><p v-if="error" role="alert">{{ error }}</p><section class="video-grid"><VideoTile v-for="feed in feeds" :key="feed.id" :token="token" :feed="feed" /></section></template>
