# 实验三：Spark ALS 与离线推荐效果评价

## 实现

- ALS 使用 **Spark MLlib `pyspark.ml.recommendation.ALS`**，显式评分模式。参数：`rank=16`、`regParam=0.12`、`maxIter=8`、`seed=42`、`implicitPrefs=False`、`coldStartStrategy=drop`。业务模型使用 `business/history_ratings.csv` 的 798,775 条真实评分；离线评价模型只使用 `evaluation/train.csv` 的 583,502 条评分。两个模型分别训练，模型清单记录训练文件 SHA-256、Spark 版本、参数和工件 SHA-256。
- ALS v2 依据**训练集**中每部电影的评分次数 `n`，将原始 ALS 预测分向 3.5 分收缩：`排序分 = 3.5 + n/(n+25) × (ALS预测分−3.5)`。评分很少的电影预测更不稳定，因此收缩得更多。25 与 3.5 是固定先验，不读取验证答案。对已评分或已收藏电影做排除；有行为的注册账号可根据自己的评分和收藏估计用户因子。用户完全无行为时使用 Cold Start。
- Popular、Content 与 ItemCF 也单独在评价训练集上重建模型，避免把完整业务历史评分用于离线评价。Popular v2 使用 `贝叶斯平滑平均分 × log(1+评分人数)` 排序，同时考虑口碑与热度；评价时仍遵守课程“候选电影扣除该用户训练评分”的规则。业务热门榜与 Cold Start 共用同一排序公式。

## 验证口径与真实结果

固定任务：`rec-course-v3-train5-1.0.0` / `temporal-v1-cold500-train5-v3` 的 **validation** 分区，共 **4,209** 位固定合格用户。每位用户候选集为 8,459 部课程目录电影扣除该用户训练集已评分电影。验证评分 `>=4.0` 为相关电影。对每人计算前 10 名命中数；`Precision@10 = 命中数 / 10`，`Recall@10 = 命中数 / 该用户验证集相关电影数`，最后对全部固定用户取宏平均。无推荐的用户仍纳入平均，不能只挑好看的用户。

| 算法 | Precision@10 | Recall@10 |
| --- | ---: | ---: |
| Content | 0.738893% | 1.086246% |
| ItemCF | 5.352815% | 10.220514% |
| ALS v2 | 2.948444% | 4.793830% |
| Popular 对照 | 3.395106% | 5.830395% |

这组数据上 ItemCF 的前 10 名命中表现最好。ALS v1 直接按原始预测分排序时只有 0.078403% / 0.091369%；v2 的训练支持度收缩提高到了 2.948444% / 4.793830%，仍低于 ItemCF。Popular v1 的贝叶斯均分加少量人数奖励为 2.618199% / 4.658054%；v2 提高评分人数权重后为 3.395106% / 5.830395%。两版策略均在相同 validation 分区比较，因此这组验证数据已用于策略选择，不能再将其当作独立测试集的无偏最终效果。截图中的参考数字不是固定标准；评价必须使用本项目冻结数据的真实计算结果。上述指标是 **Precision@10 / Recall@10**，不是分类任务的总体 accuracy。

## 复核方式

1. 在课程包根目录执行 `python -m recommender.student.build_eval_baselines`，只用固定训练集建立 Popular、Content 与 ItemCF 评价模型。
2. 安装 Java 17 与 PySpark 3.5.8，执行 `python -m recommender.student.build_als --mode evaluation`；业务服务还需 `--mode business` 模型。项目放在含空格的 Windows 路径时，Spark 训练脚本使用 `S:` 指向 `E:\recommend ag` 的本地 SUBST 盘符。
3. 执行 `python -m recommender.student.run_evaluation`。程序先产生 4,209 位用户的四份 Top-10 预测文件，经课程 `check_predictions` 检验候选集、模型和用户完整性后，才读取 validation 的相关性标签并计算指标。每种评价结果还经 `check_evaluation_result` 检验任务和模型摘要。
4. 打开 `http://127.0.0.1:8080/experiments?source=ml&algorithm=als&user=14`，再将用户 ID 改为 `55`。页面下方是三种算法加 Popular 对照的真实离线评价表。

评价模型、逐用户预测文件与课程数据都留在本机忽略目录，不上传仓库；业务 API 仅加载汇总 JSON，不接触评价评分数据。仓库中的 `reports/experiment-3/` 保存真实运行页面截图。
