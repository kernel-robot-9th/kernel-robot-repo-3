<script setup lang="ts">
import { ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import Icon from '../ui/Icon.vue'
import { adminGroups } from './navigation'
defineProps<{ section: string }>()
const route = useRoute()
const menuOpen = ref(false)
watch(() => route.fullPath, () => { menuOpen.value = false })
</script>

<template>
  <div class="admin-shell">
    <button class="mobile-menu" :aria-expanded="menuOpen" aria-controls="admin-navigation" @click="menuOpen = !menuOpen"><Icon name="menu" /> {{ menuOpen ? '메뉴 닫기' : '관리자 메뉴' }}</button>
    <aside id="admin-navigation" class="admin-sidebar" :class="{ 'is-open': menuOpen }">
      <div class="sidebar-body">
      <nav aria-label="관리자 메뉴">
        <div v-for="group in adminGroups" :key="group.label" class="nav-group">
          <p>{{ group.label }}</p>
          <RouterLink v-for="item in group.items" :key="item.section" :to="item.path" :class="{ 'is-active': section === item.section }" :aria-current="section === item.section ? 'page' : undefined"><Icon :name="item.icon" /><span>{{ item.label }}</span><span v-if="section === item.section" class="nav-indicator"></span></RouterLink>
        </div>
      </nav>
      </div>
    </aside>
    <main id="main-content" class="admin-content" tabindex="-1"><slot /></main>
  </div>
</template>
