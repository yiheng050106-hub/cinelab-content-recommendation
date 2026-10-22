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
const interestGenre = ref('')
const interestChoices = [
  { label: '喜剧 · Comedy', value: 'Comedy' }, { label: '科幻 · Sci-Fi', value: 'Sci-Fi' },
  { label: '动作 · Action', value: 'Action' }, { label: '冒险 · Adventure', value: 'Adventure' },
  { label: '剧情 · Drama', value: 'Drama' }, { label: '犯罪 · Crime', value: 'Crime' },
  { label: '惊悚 · Thriller', value: 'Thriller' }, { label: '奇幻 · Fantasy', value: 'Fantasy' },
  { label: '爱情 · Romance', value: 'Romance' }, { label: '动画 · Animation', value: 'Animation' },
]
const userPage = ref(1), users = useRemote<Page<HistoryUser>>(), ratings = useRemote<Page<Movie>>()
const ratingPage = ref(1), available = ref<Algorithm[]>([]), registryError = ref<unknown>(null)
const appActivity = ref<{ ratings: number; favorites: number } | null>(null)
const appActivityError = ref(false)
type MetricRow = { algorithm: string; model_version: string; precision_at_10: number; recall_at_10: number }
type EvaluationReport = { status: string; partition: string; user_count: number; positive_threshold: number;
  top_k: number; computed_at: string; metrics: MetricRow[] }
const evaluationError = ref<unknown>(null), evaluationPending = ref(false)
const evaluation = ref<EvaluationReport | null>(null)
const percent = (value: number) => `${(value * 100).toFixed(2)}%`
const algorithmGroups = computed(() => [
  { label: '核心算法 · 学生实现', items: available.value.filter(a => ['content', 'itemcf', 'als'].includes(a.algorithm)) },
  { label: '配套策略 · 热门与冷启动', items: available.value.filter(a => ['popular', 'cold_start'].includes(a.algorithm)) },
])
const subject = computed(() => source.value === 'ml' ? (selected.value ? `ml:${selected.value}` : '') : auth.account?.subject_key || '')
const endpoint = computed(() => !subject.value ? null : source.value === 'ml'
  ? `/demo/history-users/${selected.value}/recommendations/${algorithm.value}`
  : `/me/recommendations/${algorithm.value}${algorithm.value === 'cold_start' && interestGenre.value
    ? `?genre=${encodeURIComponent(interestGenre.value)}` : ''}`)
const registered = computed(() => available.value.find(a => a.algorithm === algorithm.value)?.status === 'registered')
const validTypedUserId = computed(() => /^[1-9][0-9]*$/.test(typedUserId.value.trim()) && Number(typedUserId.value.trim()) <= 5000)
const algorithmLabels: Record<string, string> = {
  popular: 'Popular · 热门推荐', content: 'Content · 类型推荐',
  itemcf: 'ItemCF · 物品协同过滤', cold_start: 'Cold Start · 零行为推荐',
  als: 'ALS · 矩阵分解',
}
const algorithmRules = computed(() => {
  switch (algorithm.value) {
    case 'popular': return {
      summary: '大家都在看的高口碑电影，来自真实历史评分。',
      steps: [
        '统计每部电影收到多少次评分，以及这些评分的平均分。',
        '先用全站均值平滑平均分，再乘以评分人数的对数：高口碑且很多人看过的电影排在前面。',
        source.value === 'app' ? '为当前账号跳过已经评分或收藏的电影，取前 10 部。' : '展示全站热门前 10 部，历史用户的个人喜好不改变这张榜单。',
      ],
      note: '这是热门榜；分数表示综合热度，不是预测你会打几分。',
    }
    case 'content': return {
      summary: '根据你喜欢的电影类型，寻找口味接近的其他电影。',
      steps: [
        '查看该用户过去评分和收藏的电影都属于哪些类型。',
        '高于 3 分的电影会增强相应类型偏好；低分会弱化偏好，未评分的收藏提供较轻的偏好信号。',
        '比较候选电影与这些类型偏好的接近程度，跳过已评分和已收藏的电影，选出前 10 部。',
      ],
      note: '例如喜欢喜剧，不代表只推荐喜剧；兼有相近类型的电影也可能入选。',
    }
    case 'itemcf': return {
      summary: '喜欢同一部电影的人，还共同喜欢哪些电影？',
      steps: [
        '从历史评分中找出经常被同一批人打高分的电影，建立电影之间的相似关系。',
        '用当前用户高于 3 分的电影寻找相似电影；评分越高，影响越大。未评分的收藏也会提供较轻的信号。',
        '累加相似度，排除当前用户已评分或已收藏的电影，再显示前 10 部。',
      ],
      note: '续集是另一部电影，例如《Toy Story》和《Toy Story 2》的电影 ID 不同；只有同一电影 ID 才算重复。',
    }
    case 'als': return {
      summary: '用大量用户的真实评分，学习每位用户与每部电影的隐藏偏好。',
      steps: [
        '使用 Spark MLlib 的显式反馈 ALS，在历史评分上学习用户和电影的 16 维特征。',
        '将当前用户特征与候选电影特征配对，再按该电影获得的历史评分次数收缩不可靠的预测分。',
        '过滤已评分或已收藏的电影，展示预测分最高的前 10 部。新注册账号有行为后，会根据自己的评分与收藏估计偏好。',
      ],
      note: '显示的是模型预测分，并非用户实际给出的分数；无行为的新账号请使用 Cold Start。',
    }
    case 'cold_start': return {
      summary: '新用户还没有观影记录，先从可靠的热门电影开始。',
      steps: [
        '只接受已注册且评分数、收藏数都为 0 的账号。',
        '没有个人偏好时，使用真实历史评分形成的热门排序。',
        interestGenre.value ? `已选择 ${interestGenre.value}：只保留该类型的电影，再取前 10 部。` : '未选择兴趣类型：直接展示热门前 10 部；也可选择兴趣类型试试。',
      ],
      note: '账号一旦评分或收藏，便不再符合零行为条件，可改用 Content 或 ItemCF。',
    }
    default: return {
      summary: '此算法尚未接入，当前没有真实推荐结果。',
      steps: ['请选择已接入的 Popular、Content、Cold Start 或 ItemCF。'],
      note: '页面不会展示模拟推荐列表。',
    }
  }
})

function selectAlgorithm() {
  if (algorithm.value === 'cold_start') source.value = 'app'
  updateUrl()
}
async function fetchAppActivity() {
  appActivity.value = null; appActivityError.value = false
  if (!auth.account) return
  try {
    const [ratings, favorites] = await Promise.all([
      http.get<Page<Movie>>('/me/ratings', { params: { page: 1, per_page: 1 } }),
      http.get<Page<Movie>>('/me/favorites', { params: { page: 1, per_page: 1 } }),
    ])
    appActivity.value = { ratings: ratings.data.total, favorites: favorites.data.total }
  } catch { appActivityError.value = true }
}

function updateUrl() {
  void router.replace({ path: '/experiments', query: {
    source: source.value, algorithm: algorithm.value,
    ...(source.value === 'ml' && selected.value ? { user: selected.value } : {}),
    ...(source.value === 'app' && algorithm.value === 'cold_start' && interestGenre.value
      ? { genre: interestGenre.value } : {}),
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
  evaluationPending.value = true; evaluationError.value = null
  try { evaluation.value = (await http.get<EvaluationReport>('/experiments/evaluations')).data }
  catch (e) { evaluation.value = null; evaluationError.value = e }
  finally { evaluationPending.value = false }
}
watch(() => route.query, () => {
  source.value = route.query.source === 'app' ? 'app' : 'ml'
  algorithm.value = typeof route.query.algorithm === 'string' && /^[a-z_]+$/.test(route.query.algorithm)
    ? route.query.algorithm : 'content'
  selected.value = typeof route.query.user === 'string' && /^[1-9][0-9]*$/.test(route.query.user)
    ? route.query.user : ''
  typedUserId.value = selected.value
  interestGenre.value = typeof route.query.genre === 'string' &&
    interestChoices.some(choice => choice.value === route.query.genre) ? route.query.genre : ''
}, { immediate: true })
watch(() => [selected.value, source.value], () => { ratingPage.value = 1; void fetchRatings() })
watch(() => auth.account?.account_id, () => { void fetchAppActivity() }, { immediate: true })
void fetchUsers(); void fetchRegistry(); void fetchEvaluation(); void fetchRatings()
</script>

<template>
  <div class="page">
    <div class="page-heading">
      <p class="eyebrow">RECOMMENDATION LAB</p>
      <h1>推荐实验室<span class="heading-dot">.</span></h1>
      <p>用真实评分数据对比 Popular、Content、ItemCF、ALS 与 Cold Start 的 Top-10 推荐。</p>
    </div>
    <div class="lab-notice">
      <span class="status-pill">实时结果</span>
      <p>{{ algorithmRules.summary }} 已接入算法的结果由真实数据生成。</p>
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
          <div v-if="appActivity" class="activity-counts">
            <span>评分 {{ appActivity.ratings }}</span><span>收藏 {{ appActivity.favorites }}</span>
            <strong v-if="appActivity.ratings === 0 && appActivity.favorites === 0">零评分 · 零收藏</strong>
          </div>
          <span v-else-if="appActivityError">行为数量暂不可用</span>
          <RouterLink v-if="!auth.account" to="/login" class="text-link">前往登录 →</RouterLink>
        </div>
        <template v-if="source === 'app' && algorithm === 'cold_start'">
          <label for="interest-genre">兴趣类型（选做加分）</label>
          <el-select id="interest-genre" v-model="interestGenre" clearable placeholder="不选择：使用热门榜单" @change="updateUrl">
            <el-option v-for="choice in interestChoices" :key="choice.value" :label="choice.label" :value="choice.value" />
          </el-select>
          <p class="form-hint">{{ interestGenre ? `已选择 ${interestGenre}，当前只推荐该类型电影；清除后恢复热门基线。` : '先记录热门基线，再选兴趣类型对比结果。' }}</p>
        </template>
        <label for="algorithm-select">推荐算法</label>
        <el-select id="algorithm-select" v-model="algorithm" @change="selectAlgorithm">
          <el-option-group v-for="group in algorithmGroups" :key="group.label" :label="group.label">
            <el-option v-for="a in group.items" :key="a.algorithm" :label="algorithmLabels[a.algorithm] || a.algorithm" :value="a.algorithm" />
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
        <section class="algorithm-guide" :aria-label="`${algorithmLabels[algorithm] || algorithm} 的推荐规则`">
          <div class="section-top"><h2>这套算法怎么推荐</h2><span class="status-pill">{{ algorithmLabels[algorithm] || algorithm }}</span></div>
          <p class="guide-summary">{{ algorithmRules.summary }}</p>
          <ol><li v-for="step in algorithmRules.steps" :key="step">{{ step }}</li></ol>
          <p class="guide-note">{{ algorithmRules.note }}</p>
        </section>
        <AlgorithmPanel :label="`${algorithmLabels[algorithm] || algorithm} · 推荐结果`" :endpoint="endpoint" :subject-key="subject"
          :empty-subject="source === 'ml' ? '请选择历史用户' : '登录后体验'" @refresh="fetchAppActivity" />
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
            <template v-if="evaluation">
              <div class="evaluation-context">
                <span class="status-pill">真实验证集 · {{ evaluation.user_count }} 位用户</span>
                <p>四种算法使用同一批历史用户。先用固定训练集建模，再与未参与训练的验证评分比较；评分达到 {{ evaluation.positive_threshold }} 分视为喜欢。</p>
              </div>
              <div class="table-scroll"><table class="metric-table" aria-label="Content ItemCF ALS Popular 离线评价结果">
                <thead><tr><th>算法</th><th>Precision@10</th><th>Recall@10</th></tr></thead>
                <tbody><tr v-for="row in evaluation.metrics" :key="row.algorithm">
                  <th>{{ algorithmLabels[row.algorithm] || row.algorithm }}</th>
                  <td>{{ percent(row.precision_at_10) }}</td><td>{{ percent(row.recall_at_10) }}</td>
                </tr></tbody>
              </table></div>
              <p class="metric-explain">Precision@10：推荐的 10 部中，有多少部出现在验证集的高分电影里。Recall@10：验证集的高分电影中，有多少部被推荐命中。表中是 {{ evaluation.user_count }} 位用户分别计算后取平均；短于 10 部仍以 10 为 Precision 分母。</p>
              <small class="metric-source">固定 validation 分区 · 只读离线报告 · {{ evaluation.computed_at }}</small>
            </template>
            <p v-else class="evaluation-empty">评价报告暂不可用。</p>
          </StatePanel>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.algorithm-guide { padding: 20px 24px; margin-bottom: 18px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); }
.algorithm-guide .section-top { align-items: center; }
.algorithm-guide .section-top h2 { font-size: 18px; }
.guide-summary { margin: 12px 0; font-weight: 650; }
.algorithm-guide ol { margin: 0; padding-left: 22px; color: var(--muted); line-height: 1.7; }
.algorithm-guide li + li { margin-top: 5px; }
.guide-note { margin: 12px 0 0; padding: 9px 12px; border-left: 3px solid var(--accent); background: var(--bg); color: var(--muted); font-size: 12px; }
.direct-user-input { display: flex; gap: 8px; }
.direct-user-input .el-input { min-width: 0; }
.direct-user-input .el-button { flex: 0 0 auto; }
.model-info strong { color: var(--accent); }
.activity-counts { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; align-items: center; }
.activity-counts span, .activity-counts strong { padding: 4px 8px; border: 1px solid var(--border); border-radius: 12px; font-size: 11px; }
.activity-counts strong { color: var(--accent); border-color: var(--accent); }
.evaluation-context { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin: 12px 0; }
.evaluation-context p { flex: 1 1 300px; margin: 0; color: var(--muted); line-height: 1.5; }
.metric-table { width: 100%; border-collapse: collapse; margin: 14px 0; min-width: 470px; }
.metric-table th, .metric-table td { padding: 12px 14px; border-bottom: 1px solid var(--border); text-align: left; }
.metric-table thead th { color: var(--muted); font-size: 12px; }
.metric-table tbody th { color: var(--accent); }
.metric-table tbody td { font-size: 18px; font-weight: 700; font-variant-numeric: tabular-nums; }
.metric-explain { color: var(--muted); line-height: 1.6; font-size: 13px; }
.metric-source { color: var(--muted); }
</style>
