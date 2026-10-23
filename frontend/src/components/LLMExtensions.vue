<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import http, { errorMessage } from '../api'

const props = defineProps<{ source: string; userId: string; algorithm: string }>()
type SearchMovie = { movie_id: string; movielens_title: string; title_zh: string | null;
  genres: string[]; rating_count: number }
type SearchResult = { model: string; input: string; intent: { genre: string | null; keyword: string | null };
  source: string; items: SearchMovie[] }
type Evidence = { user_id: string; algorithm: string;
  recommendation: { rank: number; score: number | null; recall_sources: string[] | null;
    recall_ranks: Record<string, number> | null;
    movie: { movie_id: string; movielens_title: string; title_zh: string | null; genres: string[] } };
  liked_history: { movie_id: string; rating: number; movielens_title: string; genres: string[] }[] }
type ExplainResult = { model: string; explanation: string; evidence: Evidence }

const prompt = ref('我想看轻松有趣的喜剧电影')
const search = ref<SearchResult | null>(null), explanation = ref<ExplainResult | null>(null)
const searchBusy = ref(false), explainBusy = ref(false)
const searchError = ref(''), explainError = ref('')
const canExplain = computed(() => props.source === 'ml' && /^[1-9][0-9]*$/.test(props.userId) &&
  ['content', 'itemcf', 'als', 'rrf'].includes(props.algorithm))

async function runSearch() {
  if (prompt.value.trim().length < 4) return
  searchBusy.value = true; search.value = null; searchError.value = ''
  try {
    search.value = (await http.post<SearchResult>('/experiments/llm/search',
      { prompt: prompt.value.trim() }, { timeout: 65000 })).data
  } catch (error) { searchError.value = errorMessage(error) }
  finally { searchBusy.value = false }
}
async function runExplain() {
  if (!canExplain.value) return
  explainBusy.value = true; explanation.value = null; explainError.value = ''
  try {
    explanation.value = (await http.post<ExplainResult>('/experiments/llm/explain',
      { ml_user_id: Number(props.userId), algorithm: props.algorithm }, { timeout: 65000 })).data
  } catch (error) { explainError.value = errorMessage(error) }
  finally { explainBusy.value = false }
}
watch(() => [props.source, props.userId, props.algorithm], () => { explanation.value = null; explainError.value = '' })
</script>

<template>
  <section class="llm-panel" aria-label="大模型推荐扩展">
    <div class="section-top"><h2>大模型推荐扩展</h2><span class="status-pill">真实电影数据 · 免费模型</span></div>
    <div class="llm-columns">
      <div class="llm-feature">
        <h3>S2 · 用自然语言找电影</h3>
        <p>模型先理解你的类型或片名需求，再从课程电影目录中检索；下方电影 ID 均来自真实数据库。</p>
        <el-input v-model="prompt" type="textarea" :rows="2" maxlength="300" show-word-limit placeholder="例如：我想看有趣的喜剧电影" />
        <el-button type="primary" :loading="searchBusy" :disabled="prompt.trim().length < 4" @click="runSearch">理解并搜索真实电影</el-button>
        <p v-if="searchError" class="llm-error" role="alert">{{ searchError }}</p>
        <div v-if="search" class="llm-result" aria-label="自然语言电影搜索结果">
          <p><strong>模型：</strong>{{ search.model }} · <strong>识别条件：</strong>{{ search.intent.genre || '不限类型' }}<span v-if="search.intent.keyword"> / {{ search.intent.keyword }}</span></p>
          <p>匹配 {{ search.items.length }} 部真实电影，按历史评分人数排序：</p>
          <ol><li v-for="movie in search.items" :key="movie.movie_id"><RouterLink :to="`/movies/${movie.movie_id}`">{{ movie.title_zh || movie.movielens_title }}</RouterLink><small>#{{ movie.movie_id }} · {{ movie.genres.join(' / ') }} · {{ movie.rating_count }} 次历史评分</small></li></ol>
        </div>
      </div>
      <div class="llm-feature">
        <h3>S4 · 可核验的推荐理由</h3>
        <p>选择历史用户和 Content、ItemCF、ALS 或 RRF。模型只根据该用户高分历史与真实 Top-1 推荐证据解释。</p>
        <p class="llm-conditions">当前条件：<strong>{{ source === 'ml' && userId ? `ml${userId}` : '请选择历史用户' }}</strong> · <strong>{{ algorithm.toUpperCase() }}</strong></p>
        <el-button type="primary" :loading="explainBusy" :disabled="!canExplain" @click="runExplain">生成 Top-1 推荐理由</el-button>
        <p v-if="explainError" class="llm-error" role="alert">{{ explainError }}</p>
        <div v-if="explanation" class="llm-result" aria-label="个性化推荐解释结果">
          <p><strong>{{ explanation.evidence.recommendation.movie.title_zh || explanation.evidence.recommendation.movie.movielens_title }}</strong> · #{{ explanation.evidence.recommendation.movie.movie_id }} · 推荐第 {{ explanation.evidence.recommendation.rank }} 名</p>
          <p class="llm-explanation">{{ explanation.explanation }}</p>
          <p><strong>可核验历史：</strong><span v-for="(movie, index) in explanation.evidence.liked_history" :key="movie.movie_id">{{ index ? '；' : '' }}{{ movie.movielens_title }}（{{ movie.rating }} 分）</span></p>
          <p v-if="explanation.evidence.recommendation.recall_ranks"><strong>算法来源：</strong><span v-for="(rank, source) in explanation.evidence.recommendation.recall_ranks" :key="source">{{ source }} #{{ rank }}　</span></p>
          <small>模型 {{ explanation.model }} · 电影、评分和排名来自 CineLab 实际数据</small>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.llm-panel { padding: 20px 24px; margin: 18px 0; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); }
.llm-panel h2 { font-size: 18px; }
.llm-columns { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; margin-top: 14px; }
.llm-feature { min-width: 0; padding: 17px; border: 1px solid var(--border); border-radius: 9px; background: var(--bg); }
.llm-feature h3 { margin: 0 0 7px; font-size: 15px; }
.llm-feature p { font-size: 12px; line-height: 1.6; color: var(--muted); }
.llm-feature .el-button { margin-top: 10px; }
.llm-conditions strong { color: var(--accent); }
.llm-feature .llm-error { color: #d06464; }
.llm-result { margin-top: 15px; padding-top: 12px; border-top: 1px solid var(--border); }
.llm-result p { margin: 6px 0; }
.llm-result strong, .llm-result a { color: var(--accent); }
.llm-result ol { margin: 8px 0 0; padding-left: 22px; }
.llm-result li { padding: 4px 0; font-size: 12px; }
.llm-result li small { display: block; color: var(--muted); }
.llm-result .llm-explanation { font-size: 14px; color: var(--text); }
.llm-result > small { color: var(--muted); }
@media(max-width: 900px) { .llm-columns { grid-template-columns: 1fr; } }
</style>
