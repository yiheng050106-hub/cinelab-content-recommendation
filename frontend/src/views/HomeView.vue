<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ArrowRight, Search, Reading } from '@element-plus/icons-vue'
import http from '../api'
import { useAuth } from '../stores/auth'
import { useRemote } from '../composables/useRemote'
import type { Movie, Page } from '../types'
import MovieCard from '../components/MovieCard.vue'
import StatePanel from '../components/StatePanel.vue'
import HomeRecommendations from '../components/HomeRecommendations.vue'
import LLMExtensions from '../components/LLMExtensions.vue'
const auth = useAuth()
const homeAlgorithm = ref('cold_start')
const { data, error, loading, load } = useRemote<Page<Movie>>()
const fetchMovies = () => load(async () => (await http.get<Page<Movie>>('/movies', { params: { per_page: 4 } })).data)
onMounted(fetchMovies)
</script>
<template>
  <div class="page home-page">
    <section class="hero">
      <div class="hero-copy"><p class="eyebrow"><span /> A MOMENT FOR CINEMA</p><h1>好电影，值得<span>再靠近一点。</span></h1><p class="hero-description">从一部电影开始，发现自己的观影偏好。<br />探索真实片库，让每一次评分留下回响。</p><div class="hero-actions"><RouterLink class="button primary" to="/movies">探索电影库 <el-icon aria-hidden="true"><ArrowRight /></el-icon></RouterLink><RouterLink class="button subtle" to="/experiments">进入推荐实验室</RouterLink></div><div class="hero-footnote"><span class="line" /> 浏览 · 记录 · 发现</div></div>
      <div class="hero-art" aria-hidden="true"><div class="orbital orbital-one" /><div class="orbital orbital-two" /><div class="film-ticket"><div class="ticket-top"><span>CINELAB</span><span>ADMIT ONE</span></div><div class="ticket-reel"><span /><span /><span /><span /><i /></div><div class="ticket-caption">THE NEXT<br /><em>discovery.</em></div><div class="ticket-bottom"><span>留一点时间，给电影。</span><span>▶</span></div></div><span class="art-label">YOUR TASTE. YOUR NEXT FILM.</span></div>
    </section>
    <div class="intro-strip"><p><el-icon aria-hidden="true"><Reading /></el-icon><strong>真实片库</strong><span>保留原始 MovieLens 电影标识</span></p><p><el-icon aria-hidden="true"><Search /></el-icon><strong>自由探索</strong><span>按片名与类型发现电影</span></p><RouterLink to="/movies">开始浏览 <span aria-hidden="true">↗</span></RouterLink></div>
    <section class="recommendation-section"><div class="section-heading"><div><p class="eyebrow">MADE FOR YOUR TASTE</p><h2>你的下一部<span class="heading-dot">.</span></h2><p class="muted">首页每次读取当前账号行为，零记录使用 Cold Start，有喜好后按评分和收藏实时推荐。</p></div><RouterLink to="/experiments" class="text-link">查看实验室 →</RouterLink></div>
      <HomeRecommendations @algorithm="homeAlgorithm = $event" />
      <div class="extension-paths" aria-label="实验四扩展入口">
        <div><strong>S1 · 多算法融合</strong><p>在实验室查看 RRF 如何汇总 Content、ItemCF、ALS 与热门排名。</p><RouterLink to="/experiments?source=app&algorithm=rrf">打开 RRF →</RouterLink></div>
        <div><strong>S3 · 行为反馈</strong><p>评分和收藏写入 Kafka，查看消费事件和兴趣变化。</p><RouterLink to="/experiments?source=app&algorithm=content#kafka-feedback">查看 Kafka 反馈 →</RouterLink></div>
      </div>
      <LLMExtensions source="app" :user-id="auth.account?.account_id || ''" :subject-label="auth.account?.login_name" :algorithm="homeAlgorithm" />
    </section>
    <section class="browse-section"><div class="section-heading"><div><p class="eyebrow">THE FILM ARCHIVE</p><h2>从片库出发<span class="heading-dot">.</span></h2><p class="muted">按原始电影编号展示，探索属于你的下一部。</p></div><RouterLink to="/movies" class="text-link">查看全部 <el-icon aria-hidden="true"><ArrowRight /></el-icon></RouterLink></div><StatePanel :loading="loading" :error="error" :empty="!!data && !data.items.length" @retry="fetchMovies"><div class="movie-grid"><MovieCard v-for="movie in data?.items" :key="movie.movie_id" :movie="movie" /></div></StatePanel></section>
  </div>
</template>

<style scoped>
.hero { min-height: 0; padding: 26px 40px; grid-template-columns: 1.5fr .65fr; align-items: center; }
.hero h1 { font-size: clamp(30px, 2.7vw, 38px); line-height: 1.3; margin: 12px 0; }
.hero .eyebrow { margin-bottom: 8px; }
.hero-description { font-size: 14px; line-height: 1.75; }
.hero-actions { margin-top: 18px; }
.hero-footnote { display: none; }
.hero-art { height: 210px; min-height: 0; transform: none; }
.film-ticket { transform: scale(.62) rotate(9deg); }
.orbital { width: 260px; height: 230px; }
.orbital-two { width: 280px; height: 190px; }
.art-label { display: none; }
.recommendation-section { margin-top: 30px; }
.extension-paths { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 12px; margin-top: 16px; }
.extension-paths > div { border: 1px solid var(--border); border-radius: 9px; padding: 14px 18px; background: var(--surface); }
.extension-paths strong { color: var(--accent); }
.extension-paths p { color: var(--muted); font-size: 12px; margin: 7px 0; }
.extension-paths a { font-size: 12px; font-weight: 700; }
@media (max-width: 700px) { .extension-paths { grid-template-columns: 1fr; } }
@media (max-width: 780px) {
  .hero { grid-template-columns: 1fr 160px; padding: 24px; gap: 12px; }
  .hero-art { height: 190px; }
  .film-ticket { transform: scale(.52) rotate(9deg); }
}
@media (max-width: 540px) {
  .hero { grid-template-columns: 1fr; padding: 22px 20px; }
  .hero h1 { font-size: 30px; }
  .hero-art { display: none; }
  .hero-actions { gap: 10px; }
  .hero-actions .button { padding: 10px 12px; }
  .recommendation-section { margin-top: 26px; }
}
</style>
