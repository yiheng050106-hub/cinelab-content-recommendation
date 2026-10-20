<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from '../stores/auth'
import http, { ApiError } from '../api'
import { useRemote } from '../composables/useRemote'
import type { Algorithm, HistoryUser, Movie, Page } from '../types'
import StatePanel from '../components/StatePanel.vue'
import PageNav from '../components/PageNav.vue'
import AlgorithmPanel from '../components/AlgorithmPanel.vue'

const route = useRoute(), router = useRouter(), auth = useAuth()
const source = ref('ml'), algorithm = ref('content'), selected = ref(''), typedUserId = ref('')
const userPage = ref(1), users = useRemote<Page<HistoryUser>>(), ratings = useRemote<Page<Movie>>()
const ratingPage = ref(1), available = ref<Algorithm[]>([]), registryError = ref<unknown>(null)
const evaluationError = ref<unknown>(null), evaluationPending = ref(false), evaluationMissing = ref(false)
const algorithmGroups = computed(() => [
  { label: '核心算法 · 学生实现', items: available.value.filter(a => ['content', 'itemcf', 'als'].includes(a.algorithm)) },
  { label: '配套策略 · 热门与冷启动', items: available.value.filter(a => ['popular', 'cold_start'].includes(a.algorithm)) },
])
const subject = computed(() => source.value === 'ml' ? (selected.value ? `ml:${selected.value}` : '') : auth.account?.subject_key || '')
const endpoint = computed(() => !subject.value ? null : source.value === 'ml'
  ? `/demo/history-users/${selected.value}/recommendations/${algorithm.value}`
  : `/me/recommendations/${algorithm.value}`)
const registered = computed(() => available.value.find(a => a.algorithm === algorithm.value)?.status === 'registered')
const validTypedUserId = computed(() => /^[1-9][0-9]*$/.test(typedUserId.value.trim()) && Number(typedUserId.value.trim()) <= 5000)

function updateUrl() {
  void router.replace({ path: '/experiments', query: {
    source: source.value, algorithm: algorithm.value,
    ...(source.value === 'ml' && selected.value ? { user: selected.value } : {}),
  } })
}
function applyUserId() {
  if (!validTypedUserId.value) return
  selected.value = typedUserId.value.trim()
  updateUrl()
}
async function fetchUsers(page = userPage.value) {
  userPage.value = page
  await users.load(async () => (await http.get<Page<HistoryUser>>('/demo/history-users', { params: { page, per_page: 20 } })).data)
}
function fetchRatings() {
  if (source.value !== 'ml' || !selected.value) return
  return ratings.load(async () => (await http.get<Page<Movie>>(
    `/demo/history-users/${encodeURIComponent(selected.value)}/ratings`,
    { params: { page: ratingPage.value, per_page: 10 } },
  )).data)
}
async function fetchRegistry() {
  try { available.value = (await http.get<{ items: Algorithm[] }>('/experiments/algorithms')).data.items; registryError.value = null }
  catch (e) { registryError.value = e }
}
async function fetchEvaluation() {
  evaluationPending.value = true; evaluationError.value = null; evaluationMissing.value = false
  try { await http.get('/experiments/evaluations') }
  catch (e) {
    if (e instanceof ApiError && e.status === 501 && e.code === 'EVALUATION_NOT_IMPLEMENTED') evaluationMissing.value = true
    else evaluationError.value = e
  } finally { evaluationPending.value = false }
}
watch(() => route.query, () => {
  source.value = route.query.source === 'app' ? 'app' : 'ml'
  algorithm.value = typeof route.query.algorithm === 'string' && /^[a-z_]+$/.test(route.query.algorithm)
    ? route.query.algorithm : 'content'
  selected.value = typeof route.query.user === 'string' && /^[1-9][0-9]*$/.test(route.query.user)
    ? route.query.user : ''
  typedUserId.value = selected.value
}, { immediate: true })
watch(() => [selected.value, source.value], () => { ratingPage.value = 1; void fetchRatings() })
void fetchUsers(); void fetchRegistry(); void fetchEvaluation(); void fetchRatings()
</script>

<template>
  <div class="page">
    <div class="page-heading">
      <p class="eyebrow">RECOMMENDATION LAB</p>
      <h1>推荐实验室<span class="heading-dot">.</span></h1>
      <p>从真实观影历史出发，观察 Content 如何找到下一部电影。</p>
    </div>
    <div class="lab-notice">
      <span class="status-pill">实时结果</span>
      <p>Content 使用电影类型和对应用户的历史评分计算推荐。历史用户只读；其他尚未接入的算法保留原状态。</p>
    </div>
    <div class="lab-layout">
      <aside class="lab-controls">
        <h2>实验设置</h2>
        <label for="subject-source">用户来源</label>
        <el-select id="subject-source" v-model="source" @change="updateUrl">
          <el-option label="MovieLens 历史用户（只读）" value="ml" />
          <el-option label="当前注册账号" value="app" />
        </el-select>
        <template v-if="source === 'ml'">
          <label for="history-user-id">历史用户 ID</label>
          <div class="direct-user-input">
            <el-input id="history-user-id" v-model="typedUserId" inputmode="numeric" placeholder="输入 14 或 55" @keyup.enter="applyUserId" />
            <el-button type="primary" :disabled="!validTypedUserId" @click="applyUserId">选择</el-button>
          </div>
          <p class="form-hint">直接输入教师指定 ID，或从下方列表选择。</p>
          <label for="history-user">浏览历史用户</label>
          <el-select id="history-user" v-model="selected" placeholder="从真实用户列表选择" @change="typedUserId = selected; updateUrl()">
            <el-option v-for="u in users.data.value?.items" :key="u.ml_user_id"
              :label="`${u.subject_key} · ${u.evaluation_role}`" :value="u.ml_user_id" />
          </el-select>
          <StatePanel v-if="users.error.value" :error="users.error.value" @retry="fetchUsers()" />
          <p v-if="users.loading.value" class="muted" role="status">正在加载用户…</p>
          <div class="user-pager">
            <el-button :disabled="userPage === 1 || users.loading.value" @click="fetchUsers(userPage - 1)">上一组</el-button>
            <span>{{ userPage }} / {{ Math.ceil((users.data.value?.total || 0) / 20) || 1 }}</span>
            <el-button :disabled="!users.data.value || userPage * 20 >= users.data.value.total || users.loading.value" @click="fetchUsers(userPage + 1)">下一组</el-button>
          </div>
        </template>
        <div v-else class="current-subject">
          <p>{{ auth.account?.login_name || '请先登录注册账号' }}</p>
          <span>{{ auth.account?.subject_key || '尚未登录' }}</span>
          <RouterLink v-if="!auth.account" to="/login" class="text-link">前往登录 →</RouterLink>
        </div>
        <label for="algorithm-select">推荐算法</label>
        <el-select id="algorithm-select" v-model="algorithm" @change="updateUrl">
          <el-option-group v-for="group in algorithmGroups" :key="group.label" :label="group.label">
            <el-option v-for="a in group.items" :key="a.algorithm" :label="a.algorithm" :value="a.algorithm" />
          </el-option-group>
        </el-select>
        <StatePanel v-if="registryError" :error="registryError" @retry="fetchRegistry" />
        <div class="model-info">
          <span>当前对象</span><strong>{{ subject || '未选择' }}</strong>
          <span>算法状态</span><strong>{{ registered ? '已接入 · 实时计算' : '尚未实现' }}</strong>
          <span>运行模式</span><strong>business · 只读实验入口</strong>
        </div>
      </aside>
      <div class="lab-results">
        <AlgorithmPanel :label="`${algorithm} · 推荐结果`" :endpoint="endpoint" :subject-key="subject"
          :empty-subject="source === 'ml' ? '请选择历史用户' : '登录后体验'" />
        <section v-if="source === 'ml'" class="history-panel">
          <div class="section-top"><h2>历史评分</h2><span class="status-pill">{{ subject || '未选择用户' }} · 只读</span></div>
          <StatePanel :loading="ratings.loading.value" :error="ratings.error.value"
            :empty="!selected || !!ratings.data.value && !ratings.data.value.items.length"
            title="选择一位历史观众" description="这里显示真实历史评分，不提供修改入口。" @retry="fetchRatings">
            <div class="table-scroll"><el-table :data="ratings.data.value?.items || []" aria-label="历史用户只读评分表">
              <el-table-column label="电影" min-width="200"><template #default="scope"><RouterLink :to="`/movies/${scope.row.movie_id}`" class="text-link">{{ scope.row.movielens_title }}</RouterLink></template></el-table-column>
              <el-table-column prop="movie_id" label="电影ID" width="100" />
              <el-table-column prop="rating" label="历史评分" width="100" />
            </el-table></div>
            <PageNav :page="ratingPage" :size="10" :total="ratings.data.value?.total || 0" @change="ratingPage = $event; fetchRatings()" />
          </StatePanel>
        </section>
        <section class="evaluation-panel">
          <div class="section-top"><h2>离线评价</h2><span class="small-label">PRECISION@10 / RECALL@10</span></div>
          <StatePanel :loading="evaluationPending" :error="evaluationError" @retry="fetchEvaluation">
            <div class="evaluation-empty"><span class="status-pill">{{ evaluationMissing ? '尚未实现' : '等待接入' }}</span>
              <p>暂无评价指标，等待离线评价程序接入。</p>
              <small>训练仅允许使用固定 train；此页面不连接 evaluation 数据库。</small></div>
          </StatePanel>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.direct-user-input { display: flex; gap: 8px; }
.direct-user-input .el-input { min-width: 0; }
.direct-user-input .el-button { flex: 0 0 auto; }
.model-info strong { color: var(--accent); }
</style>
