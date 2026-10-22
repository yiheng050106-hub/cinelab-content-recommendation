# 扩展实验：S1 RRF 与 S3 Kafka

本组完成 **S1 多算法融合推荐** 和 **S3 Kafka 用户行为反馈**。二者均接入 CineLab 推荐实验室，并使用课程电影目录、真实历史评分及实际注册账号行为；截图没有合成推荐结果。

## S1：RRF 多算法融合

- 对同一用户实时调用 Content、ItemCF、ALS、Popular，分别取得最多 50 部候选电影。
- 一部电影在某算法中排第 `r` 名，该来源贡献 `1 / (60 + r)`；所有来源贡献相加后排序，取 Top-10。同分按电影 ID 排序。
- 过滤当前用户已经评分或收藏的电影。每张推荐卡片显示各来源的实际名次，便于核验。
- 业务模型清单由 `python -m recommender.student.build_rrf` 基于当前课程数据摘要生成；融合参数保存在 `models/business/rrf-v1/fusion.json`。推荐列表由 Provider 运行时生成。

真实运行截图：

- [RRF · ml14 Top-10](docs/evidence/s1-rrf-ml14.jpg)
- [RRF · ml55 Top-10](docs/evidence/s1-rrf-ml55.jpg)

ml14 和 ml55 的 Top-10 存在差异，例如 ml14 含《The Matrix》，ml55 含《The Silence of the Lambs》。验收页可访问：

```text
http://127.0.0.1:8080/experiments?source=ml&algorithm=rrf&user=14&capture=rrf
http://127.0.0.1:8080/experiments?source=ml&algorithm=rrf&user=55&capture=rrf
```

`capture=rrf` 仅压缩页面布局以便截图，调用的仍是 `/api/v1/demo/history-users/{id}/recommendations/rrf` 真实接口。

## S3：Kafka 行为反馈

- 注册用户在 CineLab 中提交评分、收藏或取消收藏后，业务数据库先完成提交，API 再将电影 ID、类型、实际评分及收藏状态写入 Apache Kafka 主题 `cinelab-account-feedback-v1`。事件通过 `acks=all` 确认，返回主题、分区和 offset。
- API 内的消费者从主题起点回放事件，按账号和电影保存最新行为状态。高于 3 分的评分贡献 `rating - 3`，未评分或低分电影的收藏贡献 `0.8`；贡献累加为电影类型兴趣权重。
- 实验室中的「S3 · Kafka 行为反馈」面板可对真实电影 ID 评分、收藏，展示当前账号、已消费事件、兴趣权重和最近事件的 partition/offset。评分或收藏还会改变当前账号的实时推荐。
- Kafka 使用官方 `apache/kafka:4.0.2` 单节点 KRaft 镜像，只连接 CineLab 内部 Docker 网络，不映射主机端口；数据保存在 `cinelab_kafka_data` 卷。API 重启后消费者会回放保留的事件并恢复兴趣状态。

真实运行截图（测试账号 `extdemo1792674788`）：

- [两条已消费事件：评分 #1、收藏 #2](docs/evidence/s3-kafka-feedback-1.jpg)
- [给电影 #3 打 5 分后，新增 offset 2，Comedy 兴趣从 2.00 增至 4.00](docs/evidence/s3-kafka-feedback-2.jpg)

验收页：`http://127.0.0.1:8080/experiments?source=app&algorithm=rrf&capture=feedback`。`capture=feedback` 仅调整显示布局，评分与消费均调用真实接口。测试账号密码不在仓库中。

## 本机复现

先按课程包 README 完成离线镜像导入、数据库初始化及模型生成，确保 `models/business` 和 `data/packages` 已就绪。安装 Node.js、Python、Docker Desktop 后，在项目根目录执行：

```powershell
docker pull apache/kafka:4.0.2
./deployment/build-extension-images.ps1
./deployment/start-extensions.ps1 -Action Start
```

打开 `http://127.0.0.1:8080/experiments`。RRF 选择历史用户 `14`、`55`；Kafka 反馈需要先登录一个注册账号。扩展脚本与课程受摘要保护的启动脚本分开，保留原有数据库、镜像和密钥配置。

**运行边界：** Kafka 停机时评分、收藏仍写入业务数据库，但 API 会明确返回 `kafka_event.status=unavailable`，实验室显示队列不可用；这时该操作不会计入 Kafka 兴趣状态。演示前应确认四个容器健康运行。
