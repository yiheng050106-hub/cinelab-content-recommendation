# Content 推荐实验实现

本次只实现业务模式的 `content` 算法。推荐结果由实时请求中的用户历史评分与真实电影类型计算，不保存静态推荐清单，也不读取评价集的 validation/test 或 cold query。

## 实现与数据边界

- `recommender/student/build_content.py` 校验冻结 `movies.csv`、`training-catalog.csv` 和 `business/history_ratings.csv` 的摘要，然后拟合类型 IDF 与电影评分的平滑先验，生成 `models/business/content-genres-v1/` 下的工件和模型清单。
- `recommender/student/content.py` 对每个请求通过现有 `read_history` 读取 `ml:<id>` 或 `app:<id>` 的评分。高于 3 分的评分增加相应类型偏好，低于 3 分的评分弱化偏好。未评分的收藏只作为较弱的隐式信号，不伪造评分。
- 候选来自批准的 8,459 部电影目录，排除该用户已评分或已收藏的电影。按类型 TF-IDF 余弦相似度排序，以从业务评分拟合的轻量平滑先验区分相近候选；同分按电影 ID 数值升序。无可用偏好时返回空列表。
- `contracts.py` 仅为 `content` 注册 Provider，其余未实现算法保持原有 501 状态。模型清单经现有 `check_model` 校验数据版本、输入摘要和工件摘要。
- 实验室页面通过真实推荐接口取 Top-10，再从现有电影详情接口取片名、年份和类型；卡片显示排名与模型分数。可直接输入历史用户 ID，URL 保留所选用户和算法。前端没有内置任何推荐电影 ID。

业务模型和评价模型不能混用。`ml:55` 在冻结评价划分中标为 cold，但本次截图与推荐调用是 **business** 模式，使用业务历史评分；不能据此声称离线 cold-start 评价已完成。

## 从课程包重新运行

在已初始化的课程项目根目录运行：

```powershell
py -3 -m recommender.student.build_content
py -3 -m recommender.check model models/business/content-genres-v1/manifest.json --mode business
$env:TEMP = 'E:\recommend ag\.tmp-build'  # 按实际机器改成已有的纯英文临时目录
$env:TMP = $env:TEMP
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\deployment\build.ps1 -Target all
```

生成模型位于 `.gitignore` 排除的 `models/business/`，冻结数据也不进入 Git 仓库。新机器先按教师快速开始完成环境配置、镜像导入、首次初始化，再生成模型和构建代码。普通重启后使用 `build.ps1 -Action Start` 启动已构建镜像；课程包的 `04-启动推荐系统.bat` 会恢复教师原阶段 A 镜像。

## 实测

本机接口 `GET /api/v1/demo/history-users/{id}/recommendations/content?limit=10` 对 `ml:14` 与 `ml:55` 均返回 `content-genres-v1` 的 10 条有效结果，两个 Top-10 无交集。`ml:14` 的高评分电影以 Comedy 为主，推荐也偏 Comedy；`ml:55` 的高评分电影集中 Crime、Drama、Thriller、Action，推荐列表对应这些类型。运行截图在本机 `E:\recommend ag\reports\content-ml14.jpg` 与 `content-ml55.jpg`，提交时请上传截图文件，不要把冻结数据、密钥或本地模型工件推到 GitHub。
