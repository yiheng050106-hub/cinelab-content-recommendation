<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import http from '../api'
import { useAuth } from '../stores/auth'
import type { Account, AlgorithmResult, Movie } from '../types'
import StatePanel from './StatePanel.vue'

type Behavior = { ratings: number; favorites: number; positive_ratings: number; version: string;
  latest: { kind: string; movie_id: string; title: string; rating: string | null; at: string } | null;
  top_genres: { genre: string; weight: number }[] }
type HomeResult = { account: Account; behavior: Behavior; strategy: { algorithm: string; reason: string };
  recommendation: AlgorithmResult; movies: Movie[] }

const auth = useAuth()
const emit = defineEmits<{ algorithm: [value: string] }>()
const result = ref<HomeResult | null>(null), error = ref<unknown>(null), loading = ref(false)
let run = 0

async function refresh() {
  const seq = ++run
  if (!auth.account) { result.value = null; emit('algorithm', 'cold_start'); return }
  loading.value = true; error.value = null
  try {
    const response = (await http.get<HomeResult>('/me/recommendations/home')).data
    if (seq !== run) return
    result.value = response
    emit('algorithm', response.strategy.algorithm)
  } catch (cause) { if (seq === run) error.value = cause }
  finally { if (seq === run) loading.value = false }
}
function onVisible() { if (document.visibilityState === 'visible' && auth.account) void refresh() }
watch(() => auth.account?.account_id, () => { void refresh() }, { immediate: true })
onMounted(() => document.addEventListener('visibilitychange', onVisible))
onBeforeUnmount(() => { run++; document.removeEventListener('visibilitychange', onVisible) })
defineExpose({ refresh })
</script>

<template>
  <section id="home-recommendations" class="home-personal" aria-label="当前账号首页推荐">
    <div class="home-personal-head">
      <div><p class="eyebrow">REAL-TIME PICKS</p><h2>为 {{ auth.account?.login_name || '你' }} 选片<span class="heading-dot">.</span></h2>
        <p class="muted">{{ result?.strategy.reason || '登录后根据你的真实行为生成推荐。' }}</p></div>
      <el-button :disabled="!auth.account || loading" :loading="loading" @click="refresh">重新计算推荐</el-button>
    </div>
    <div v-if="!auth.account" class="home-login"><p>登录后查看专属推荐；零行为账号从 Cold Start 热门榜开始。</p><RouterLink class="button primary" to="/login">登录查看 →</RouterLink></div>
    <StatePanel v-else :loading="loading" :error="error" @retry="refresh">
      <template v-if="result">
        <div class="evidence-bar">
          <strong>{{ result.strategy.algorithm.toUpperCase() }} · 当前账号 {{ result.account.subject_key }}</strong>
          <span>评分 {{ result.behavior.ratings }} · 收藏 {{ result.behavior.favorites }}</span>
          <span>行为版本 {{ result.behavior.version }}</span>
          <span>本次计算 {{ new Date(result.recommendation.generated_at).toLocaleString('zh-CN') }}</span>
        </div>
        <div v-if="result.behavior.latest" class="latest-behavior">
          <span>最近参与计算的行为</span><strong>{{ result.behavior.latest.kind === 'rating' ? '评分' : '收藏' }} · {{ result.behavior.latest.title }}</strong>
          <span v-if="result.behavior.latest.rating">{{ result.behavior.latest.rating }} 分</span>
          <small>#{{ result.behavior.latest.movie_id }} · {{ result.behavior.latest.at }}</small>
        </div>
        <div v-if="result.behavior.top_genres.length" class="taste-tags"><span>当前偏好</span><b v-for="item in result.behavior.top_genres" :key="item.genre">{{ item.genre }} {{ item.weight }}</b></div>
        <p v-if="!result.movies.length" class="muted">当前没有可推荐的候选电影；可以先评价或收藏一部电影。</p>
        <ol v-else class="home-picks"><li v-for="(movie, index) in result.movies" :key="movie.movie_id">
          <span class="pick-rank">{{ String(index + 1).padStart(2, '0') }}</span>
          <div><RouterLink :to="`/movies/${movie.movie_id}`">{{ movie.title_zh || movie.movielens_title }}</RouterLink>
            <small>#{{ movie.movie_id }} · {{ movie.genres.slice(0, 3).join(' / ') }} · {{ result.recommendation.items[index]?.score?.toFixed(3) ?? '—' }}</small></div>
        </li></ol>
        <p class="recommendation-proof">推荐接口每次读取当前账号评分和收藏；新增行为后返回新的行为版本，并排除已评分或收藏的电影。</p>
      </template>
    </StatePanel>
  </section>
</template>

<style scoped>
.home-personal { padding: 22px 24px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); }
.home-personal-head { display: flex; align-items: end; justify-content: space-between; gap: 20px; margin-bottom: 15px; }
.home-personal h2 { font-size: 25px; margin: 5px 0; }
.home-personal .muted { margin: 5px 0 0; }
.home-login { display: flex; align-items: center; justify-content: space-between; gap: 16px; color: var(--muted); }
.evidence-bar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; padding: 11px 13px; background: #243b36; border: 1px solid #ad945e55; border-radius: 7px; font-size: 12px; }
.evidence-bar strong { color: var(--accent); }
.evidence-bar span { color: var(--text); }
.latest-behavior { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 10px; padding: 9px 12px; border-left: 3px solid var(--accent); background: var(--bg); font-size: 12px; }
.latest-behavior > span:first-child,.latest-behavior small { color: var(--muted); }
.latest-behavior strong { color: var(--accent); }
.taste-tags { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; margin: 10px 0; font-size: 12px; color: var(--muted); }
.taste-tags b { border: 1px solid var(--border); border-radius: 20px; padding: 3px 9px; color: var(--text); font-weight: 500; }
.home-picks { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; padding: 0; margin: 12px 0 0; list-style: none; }
.home-picks li { display: flex; gap: 12px; min-width: 0; padding: 10px 12px; background: var(--bg); border: 1px solid var(--border); border-radius: 7px; }
.pick-rank { color: var(--accent); font: 21px Georgia,serif; }
.home-picks li div { min-width: 0; }
.home-picks li a { font-size: 13px; font-weight: 650; }
.home-picks li a:hover { color: var(--accent); }
.home-picks li small { display: block; color: var(--muted); font-size: 11px; margin-top: 4px; }
.recommendation-proof { margin: 12px 0 0; color: var(--muted); font-size: 11px; }
@media(max-width: 780px) { .home-picks { grid-template-columns: 1fr; } .home-personal-head { align-items: start; } }
</style>
