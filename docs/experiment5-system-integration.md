# 实验五：首页推荐与系统联调

## 实现方法

- 首页通过当前登录会话调用 `GET /api/v1/me/recommendations/home`。接口从数据库读取本账号的评分和收藏，再调用现有推荐服务计算 Top-10；电影名称和类型来自课程片库。零行为账号使用 Cold Start；有正向评分或收藏时使用 Content；只有非正向评分时使用 Popular。候选不足时依次回退 ItemCF、Popular。
- 返回值包括账号、采用的算法、当前行为数量、最近一条行为、类型偏好、行为版本和推荐电影。行为版本由评分、收藏、更新时间生成。页面在进入首页、账号切换或返回浏览器时读取最新结果，也提供“重新计算推荐”按钮。
- 电影详情页保存评分或收藏后可直接跳回首页。实验室中提交行为后自动刷新推荐卡片。个人中心读取相同账号的评分与收藏，可交叉核对。
- 首页提供 S1 RRF、S3 Kafka 的入口，并直接嵌入可操作的 S2 自然语言电影搜索和 S4 当前账号推荐解释。S4 只依据实际评分、收藏和实时推荐候选生成可核验理由。模型密钥仅保存在本机忽略的密钥文件中。

## 同一账号的真实前后对比

2026-10-23 在本机运行环境新建测试账号 `home_demo_1023143427`（`app:5`），先确认个人中心为 0 条评分、0 条收藏，然后在电影详情页给 `Toy Story (1995)`（电影 `#1`）评 5 分。以下数值来自前后两次真实接口响应和浏览器页面：

| 条件 | 行为版本 | 算法 | Top-1 | 推荐数量 |
| --- | --- | --- | --- | ---: |
| 评分 0、收藏 0 | `4f53cda18c2b` | Cold Start | `#318` Shawshank Redemption | 10 |
| `#1` 评分 5、收藏 0 | `48ad507dedd5` | Content | `#3114` Toy Story 2 | 10 |

评分后页面显示最近参与计算的行为为 `#1`、5 分，类型偏好含 Adventure、Animation、Children、Comedy。`#1` 没有再次出现在 Top-10。两个行为版本不同，说明接口读取并纳入了新增评分；两张首页截图来自同一账号。

## 提交截图

以下图片均截自本机真实运行的 CineLab 浏览器页面，保留了账号、输入条件及结果。可直接选择前五张按学习通要求提交，其余可用于说明其他扩展功能。

1. [新增行为前：首页 Cold Start Top-10](evidence/integration-home-before.jpg)
2. [在电影详情页新增 5 分评分](evidence/integration-rating-action.jpg)
3. [新增行为后：首页 Content Top-10 与行为依据](evidence/integration-home-after.jpg)
4. [S1 RRF：入口、当前账号、融合来源与 Top-10](evidence/integration-s1-rrf.jpg)
5. [S3 Kafka：入口、真实评分事件与消费者兴趣](evidence/integration-s3-kafka.jpg)
6. [S2：自然语言输入及真实电影搜索结果](evidence/integration-s2-home.jpg)
7. [S4：当前账号评分与 Top-1 可核验推荐理由](evidence/integration-s4-home.jpg)
8. [个人中心：同一账号的评分记录与首页推荐入口](evidence/integration-profile.jpg)

## 演示步骤

1. 启动 Docker Desktop，在项目根目录执行 `./deployment/start-extensions.ps1 -Action Start`，打开 `http://127.0.0.1:8080` 并登录测试账号。
2. 在首页查看当前账号的 Top-10 与行为版本。若要现场重演“零行为前后对比”，新注册一个空账号，先截图，再给任意真实电影评分或收藏，返回首页点“重新计算推荐”。
3. 在个人中心核对评分/收藏；在推荐实验室选择当前账号，切换 Content、ItemCF、ALS、RRF，确认结果可生成。
4. 从首页点击 RRF 与 Kafka 入口查看扩展功能；在首页直接输入自然语言运行 S2，并点击 S4 生成当前账号解释。

测试账号凭据与接口完整响应只保存在本机工作目录外的 `.setup` 中，未纳入 Git。
