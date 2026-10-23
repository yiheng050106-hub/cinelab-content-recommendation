# 实验四扩展：S2 自然语言找电影与 S4 个性化推荐解释

## 实现方式

**S2**：用户在推荐实验室输入自然语言需求。后端调用 OpenRouter 的 `nvidia/nemotron-3.5-lightning:free`，只让模型识别电影类型和明确提到的片名关键词。服务端随后用识别条件查询课程 `movies` 与 `history_ratings` 表，按真实历史评分人数排序并返回前 10 部电影及电影 ID。模型不负责生成电影清单，因此不会把虚构片名当作检索结果。

**S4**：用户选定历史用户和 Content、ItemCF、ALS 或 RRF 后，服务端实时调用对应算法取得 Top-1 推荐，再读取该用户真实的高分评分历史与电影类型。模型从这批证据中选择最能解释推荐的一部高分电影；服务端校验电影 ID 确属该用户历史，并计算推荐电影与其共享的类型。最终展示的片名、评分、类型和排名全部由程序从真实数据组织，同时展示六条历史评分供核验。模型选择不合法时返回错误，不伪造理由。

两项功能位于同一个“推荐实验室”页面的“大模型推荐扩展”区域。S2 和 S4 的请求分别使用 `/api/v1/experiments/llm/search` 和 `/api/v1/experiments/llm/explain`，与现有算法入口并存。免费模型是第三方服务，受其可用性与速率限制；不可用时页面显示错误，不返回模拟结果。

## 本机运行与密钥

密钥保存在本机 `deployment/openrouter.key`，作为 Docker secret 挂载到 API 容器；该文件被 `.gitignore` 排除。`deployment/llm_host_bridge.py` 是 Windows 主机到 OpenRouter 的最小转发器，仅接受持有同一密钥的请求，运行时不记录密钥或模型输出。当前机器的容器无法直接建立到 OpenRouter 的 HTTPS 连接，因此通过 `host.docker.internal:18765` 访问本机转发器。任何公开仓库中都不应提交密钥、运行配置或容器密钥文件。

已完成本机课程镜像与数据初始化后，启动 Docker Desktop，再执行：

```powershell
./deployment/build-extension-images.ps1
./deployment/start-extensions.ps1 -Action Start
```

打开 `http://127.0.0.1:8080/experiments`。S2 可输入“我想看轻松有趣的喜剧电影”或“想看紧张刺激的科幻电影”；S4 可分别选择 `ml14 + Content`、`ml55 + ItemCF` 并点击“生成 Top-1 推荐理由”。

## 真实运行截图

- [S2：喜剧自然语言输入与真实 Top-10](evidence/s2-comedy.jpg)
- [S2：科幻自然语言输入与不同的真实 Top-10](evidence/s2-scifi.jpg)
- [S4：ml14 + Content 的解释及历史证据](evidence/s4-ml14.jpg)
- [S4：ml55 + ItemCF 的解释及历史证据](evidence/s4-ml55.jpg)

这四张截图从运行中的浏览器页面截取，显示功能入口、输入条件和真实结果。两组 S2 结果及两组 S4 证据均不同。
