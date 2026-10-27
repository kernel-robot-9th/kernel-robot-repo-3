<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from './api'
import VideoTile from './VideoTile.vue'
const props = defineProps<{ token: string; feedIds?: string[]; showTools?: boolean }>()
const feeds = ref<{ id: string; label: string; owner: string; transport: string; whep_url?: string }[]>([])
const error = ref('')
const loading = ref(true)
const visibleFeeds = computed(() => feeds.value.filter(feed => !props.feedIds || props.feedIds.includes(feed.id)))
async function load() { loading.value = true; error.value = ''; try { feeds.value = (await api<{ items: typeof feeds.value }>('/admin/video', props.token)).items } catch (e) { error.value = e instanceof Error ? e.message : '영상 목록을 불러오지 못했습니다.' } finally { loading.value = false } }
onMounted(load)
</script>
<template><div v-if="error" class="alert danger" role="alert">{{ error }} <button @click="load">다시 불러오기</button></div><div v-else-if="loading" class="panel empty-state" role="status">영상 불러오는 중…</div><section v-else-if="visibleFeeds.length" class="video-grid" :class="{ 'single-feed': visibleFeeds.length === 1 }"><VideoTile v-for="feed in visibleFeeds" :key="feed.id" :token="token" :feed="feed" :show-tools="showTools" /></section><div v-else class="panel empty-state"><h3>영상 미등록</h3></div></template>
