<script setup lang="ts">
import { computed, onScopeDispose, ref, watch } from 'vue'
import { Connection } from '@element-plus/icons-vue'
import http, { ApiError } from '../api'
import StatePanel from './StatePanel.vue'
import type { AlgorithmResult, Movie } from '../types'

const props = withDefaults(defineProps<{
  endpoint: string | null
  label: string
  subjectKey?: string
  emptySubject?: string
}>(), { emptySubject: '登录后体验', subjectKey: '' })
const emit = defineEmits<{ refresh: [] }>()
const loading = ref(false), error = ref<unknown>(null), unavailable = ref(false)
const result = ref<AlgorithmResult | null>(null)
const films = ref<Record<string, Movie>>({})
const highestScore = computed(() => Math.max(0, ...result.value?.items.map(item => item.score ?? 0) || []))
const resultMethod = computed(() => ({
  popular: '评分数量与平均分', content: '电影类型与历史偏好',
  itemcf: '相似电影与评分历史', cold_start: result.value?.items[0]?.recall_sources?.includes('genre_filtered_popular')
    ? '所选兴趣类型与热门排序' : '零行为热门回退',
}[result.value?.algorithm || ''] || '真实评分数据'))
const resultScope = computed(() => result.value?.algorithm === 'popular' ? 'GLOBAL TOP'
  : result.value?.algorithm === 'cold_start' ? 'COLD START TOP' : 'PERSONALIZED TOP')
let run = 0
onScopeDispose(() => { run++ })

function scoreWidth(score: number | null) {
  return score === null || highestScore.value <= 0 ? '0%' : `${Math.max(4, score / highestScore.value * 100)}%`
}

async function load() {
  const seq = ++run
  error.value = null; result.value = null; films.value = {}; unavailable.value = false; loading.value = false
  if (!props.endpoint) return
  loading.value = true
  try {
    const response = await http.get<AlgorithmResult>(props.endpoint)
    if (seq !== run) return
    result.value = response.data
    const details = await Promise.allSettled(response.data.items.map(item =>
      http.get<Movie>(`/movies/${encodeURIComponent(item.movie_id)}`)))
    if (seq !== run) return
    const resolved: Record<string, Movie> = {}
    details.forEach((detail, index) => {
      if (detail.status === 'fulfilled') resolved[response.data.items[index].movie_id] = detail.value.data
    })
    films.value = resolved
  } catch (e) {
    if (seq !== run) return
    if (e instanceof ApiError && e.status === 501 && e.code === 'ALGORITHM_NOT_IMPLEMENTED') unavailable.value = true
    else error.value = e
  } finally { if (seq === run) loading.value = false }
}
function refresh() {
  emit('refresh')
  void load()
}
watch(() => props.endpoint, load, { immediate: true })
</script>

<template>
  <section class="algorithm-panel" :aria-label="label">
    <div class="section-top"><h3>{{ label }}</h3><div class="result-actions"><span class="small-label">LIVE RECOMMENDATION</span><el-button :disabled="!endpoint || loading" @click="refresh">重新生成</el-button></div></div>
    <StatePanel :loading="loading" :error="error" @retry="load">
      <div v-if="!endpoint || unavailable" class="algorithm-empty" role="status">
        <div class="algorithm-symbol"><el-icon aria-hidden="true"><Connection /></el-icon></div>
        <div><span class="status-pill">{{ !endpoint ? emptySubject : '尚未实现' }}</span><h3>{{ !endpoint ? '选择观众，开始探索' : '下一部好电影，等待算法发现' }}</h3><p>{{ !endpoint ? '先选择历史用户或登录注册账号。' : '当前算法尚未接入。' }}</p></div>
        <RouterLink v-if="!endpoint && emptySubject === '登录后体验'" class="text-link" to="/login">前往登录 →</RouterLink>
      </div>
      <div v-else-if="result" class="content-results">
        <div class="result-hero">
          <div><span class="result-eyebrow">{{ resultScope }} {{ result.items.length }}</span><h4>{{ result.algorithm.toUpperCase() }} <span>为 {{ subjectKey || '当前账号' }} 推荐</span></h4></div>
          <div class="result-meta"><span>模型 {{ result.model_version }}</span><span>依据：{{ resultMethod }} · {{ result.runtime_mode }}</span></div>
        </div>
        <p v-if="!result.items.length" class="result-empty">当前用户暂无可用的内容偏好或候选电影。</p>
        <ol v-else class="recommendation-grid">
          <li v-for="item in result.items" :key="item.movie_id" class="recommendation-card">
            <span class="recommendation-rank">{{ String(item.rank).padStart(2, '0') }}</span>
            <div class="recommendation-body">
              <RouterLink :to="`/movies/${item.movie_id}`" class="recommendation-title">{{ films[item.movie_id]?.title_zh || films[item.movie_id]?.movielens_title || `电影 #${item.movie_id}` }}</RouterLink>
              <p class="recommendation-subtitle">#{{ item.movie_id }}<span v-if="films[item.movie_id]?.release_year"> · {{ films[item.movie_id]?.release_year }}</span></p>
              <div class="recommendation-genres"><span v-for="genre in films[item.movie_id]?.genres.slice(0, 3) || []" :key="genre">{{ genre }}</span></div>
              <div v-if="item.score !== null" class="recommendation-score"><div class="score-track"><div class="score-fill" :style="{ width: scoreWidth(item.score) }"></div></div><strong>{{ item.score.toFixed(3) }}</strong></div>
            </div>
          </li>
        </ol>
        <p class="result-footnote">依据 {{ resultMethod }} 排序；推荐结果由真实数据计算，电影资料来自课程目录。评分或收藏后可点“重新生成”查看最新结果。</p>
      </div>
    </StatePanel>
  </section>
</template>

<style scoped>
.result-actions { display: flex; align-items: center; gap: 12px; }
.content-results { padding: 20px; }
.result-hero { display: flex; justify-content: space-between; align-items: end; gap: 20px; padding: 20px 24px; margin-bottom: 18px; border-radius: 10px; background: linear-gradient(120deg, #29443e, #1b2c2c); border: 1px solid #d6b4764a; }
.result-eyebrow { color: var(--accent); font-size: 10px; letter-spacing: .18em; font-weight: 700; }
.result-hero h4 { margin: 8px 0 0; font-size: 23px; line-height: 1.25; }
.result-hero h4 span { color: #e2c996; font-weight: 400; }
.result-meta { display: flex; flex-direction: column; gap: 4px; color: var(--muted); font-size: 11px; text-align: right; }
.recommendation-grid { list-style: none; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin: 0; padding: 0; }
.recommendation-card { display: flex; gap: 16px; min-height: 121px; padding: 16px; border: 1px solid var(--border); border-radius: 9px; background: var(--surface); }
.recommendation-rank { flex: 0 0 32px; font: 28px Georgia, serif; line-height: 1; color: var(--accent); }
.recommendation-body { min-width: 0; flex: 1; }
.recommendation-title { display: block; font-size: 15px; font-weight: 650; line-height: 1.35; overflow-wrap: anywhere; }
.recommendation-title:hover { color: var(--accent); }
.recommendation-subtitle { margin-top: 4px; color: var(--muted); font-size: 11px; }
.recommendation-genres { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 8px; }
.recommendation-genres span { padding: 1px 7px; border: 1px solid var(--border); border-radius: 12px; color: var(--muted); font-size: 10px; }
.recommendation-score { display: flex; align-items: center; gap: 10px; margin-top: 9px; }
.score-track { height: 4px; flex: 1; background: #d8c1942e; border-radius: 9px; overflow: hidden; }
.score-fill { height: 100%; background: var(--accent); border-radius: inherit; }
.recommendation-score strong { color: var(--accent); font-variant-numeric: tabular-nums; font-size: 11px; }
.result-empty { padding: 20px; color: var(--muted); }
.result-footnote { color: var(--muted); font-size: 11px; padding: 14px 2px 0; }
@media(max-width: 1100px) { .recommendation-grid { grid-template-columns: 1fr; } }
@media(max-width: 780px) { .result-hero { align-items: start; flex-direction: column; } .result-meta { text-align: left; } }
</style>
