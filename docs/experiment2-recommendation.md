# 实验二：Popular、Cold Start 与 ItemCF

## 数据和训练

运行 `py -3 -m recommender.student.build_experiment2`。脚本先校验课程冻结包的文件大小、SHA-256、列名和 798,775 条业务历史评分，再用批准的 8,459 部电影目录训练三个业务模型。模型工件和清单保存在被 `.gitignore` 排除的 `models/business/`，不会把评分原表或静态结果推送到 GitHub。可分别运行：

```powershell
py -3 -m recommender.check model models/business/popular-bayes-v1/manifest.json --mode business
py -3 -m recommender.check model models/business/cold-popular-v1/manifest.json --mode business
py -3 -m recommender.check model models/business/itemcf-cobehavior-v1/manifest.json --mode business
```

### Popular

统计每部电影的评分次数 `n`、总分与平均分。排序分数为 `(总分 + 100 × 3.5) / (n + 100) + 0.18 × log(1+n) / log(1+最大评分次数)`。贝叶斯平滑避免极少数高分电影冲到榜首，评分次数加成体现热度。所有电影按分数降序、电影 ID 升序稳定排序，接口实时返回前 10 条。

### Cold Start

只接受已注册的业务账号。每次请求都从业务库读取当前账号评分和收藏；若不为零则拒绝冷启动实验。零行为时使用上述真实评分训练的 Popular 排名回退，不创建模拟用户偏好，也不内置电影 ID。实验账号 `ehng`（`app:2`）在截图时评分 0、收藏 0。

**选做兴趣类型：** 在实验室的 Cold Start 设置里可选择 Comedy、Sci-Fi 等电影类型。选中后，请求携带 `genre` 参数，后端在同一真实热门榜单中筛出课程 `movies.csv` 标注该类型的电影，再返回按热门分数排序的 Top-10；清除选项恢复原榜单。类型和电影特征来自已校验的冻结数据，没有预置推荐清单。零评分、零收藏的要求始终保留。

本机对 `app:2` 的实际验证：未选择兴趣时 Top-10 为 `318,858,50,2959,296,527,1221,2571,1193,1203`；选择 Comedy 后为 `296,1136,750,2324,1197,356,608,202439,1234,4973`，两组仅有 1 部重合。

### ItemCF

以至少 4.0 分为正反馈，训练时每个历史用户最多保留按评分和时间排序的 30 部最强正反馈电影，避免活跃用户主导配对。统计电影对在真实用户中的加权共现次数；单用户权重按其正反馈数量的平方根缩减。相似度用两部电影各自的正反馈用户数归一化，并按共现支持度收缩；低于 2 个共同用户的电影对不保留，每部电影最多保存 80 个邻居。

请求时读取选中用户的真实历史评分，将高于 3 分的已评电影当作种子，以 `(评分−3) × 物品相似度` 累加候选分数；未评分的收藏仅提供 0.8 的弱隐式权重。排除已评分或已收藏的电影，然后按分数降序给出 Top-10。相似度模型来自所有历史用户，在线排序则由当前用户自身的历史决定。ml14 与 ml55 的 Top-10 不同。

## 系统与验收

三个 Provider 在 `recommender/contracts.py` 注册，并复用原有模型摘要校验、推荐结果校验和业务 API。实验室可切换算法及历史用户；选择 Cold Start 时自动切换到当前注册账号。页面显示真实登录名、用户 ID、评分数和收藏数，推荐卡片展示排名、电影、类型、模型版本与依据。

本机运行截图：

- `reports/experiment2-popular.jpg`：Popular Top-10。
- `reports/experiment2-cold-ehng.jpg`：账号 `ehng` 的 Cold Start Top-10，显示评分 0、收藏 0。
- `reports/experiment2-itemcf-ml14.jpg`：历史用户 `ml14` 的 ItemCF Top-10。
- `reports/experiment2-itemcf-ml55.jpg`：历史用户 `ml55` 的 ItemCF Top-10。
- `reports/experiment2-cold-comedy.jpg`：同一零行为账号选择 Comedy 后的 Top-10，与未选择兴趣时的截图对比。

上述截图来自实际运行的 `http://127.0.0.1:8080/experiments`，不是示意图。新机器必须先按课程环境指南导入数据和 Docker 镜像、生成本地模型，再构建学生 API/Web 镜像。镜像、数据库、密钥与本地运行设置不进入仓库。
