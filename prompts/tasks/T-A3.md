# T-A3 — 一行健康检查(`ai-daily doctor`)

> 任务来源:`资深架构师优化建议_产品化.md` §#3 · 批次:1(地基)
> 优先级:P0 · 预估代码量:300~400 行 · 依赖:无

## 任务定义

- **文档来源**:`资深架构师优化建议_产品化.md` §二.3
- **目标**:一行命令自检整个系统是否可跑,主动给出修复建议
- **现状**:跑 `run_daily.py --full` 中途崩才发现 key 过期/playwright 没装/端口冲突
- **落地后**:
  ```bash
  python main.py doctor
  # 输出:
  # ✅ Python 3.14.0 (需要 ≥3.10)
  # ✅ .env 中 ANYSEARCH_API_KEY 已配置
  # ✅ playwright 已安装,chromium 已下载
  # ⚠️  LLM 配置:仅 OPENAI_API_KEY,未配 ARK_*;推荐两者都配(降级)
  # ✅ data/raw 最近 7 天有产出
  # ✅ data/reports 最近 7 天有 PDF
  # ✅ 缓存目录 data/cache 写入正常
  # ✅ runlog 最近 7 天 7/7 成功
  # ─────────
  # 总评:健康 ✓
  ```

## 涉及文件(必动)

- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/app/utils/doctor.py`(~250 行)
- 新建:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/tests/test_doctor.py`(≥6 个用例)
- 修改:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/main.py`(注册 `doctor` 子命令)
- 修改:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/使用实操文档.md`
- 修改:`/Users/weike/IdeaProjects/cmjt/0-应用创新/response-api/AI财经日报/架构评审与优化计划.md`

## 自检清单(每项给友好提示)

| # | 检查项 | 友好提示 |
|---|---|---|
| 1 | Python 版本 ≥3.10 | `需要 Python 3.10+,当前 X.Y` |
| 2 | `.env` 存在,`ANYSEARCH_API_KEY` 非空 | `cp .env.example .env 并填入 ANYSEARCH_API_KEY` |
| 3 | 至少一组 LLM 配置(ARK_* 或 OPENAI_*) | `推荐至少配 OPENAI_API_KEY 或 ARK_API_KEY` |
| 4 | `playwright` 已安装且 chromium 已下载 | `pip install playwright && playwright install chromium` |
| 5 | `data/raw/{today}/` 与 `data/reports/{today}/` 最近 7 天有产出 | `近 7 天无产出,跑一次 run_daily.py --full` |
| 6 | `data/cache/` 写入权限 | `chmod 755 data/cache` |
| 7 | `logs/` 写入权限 | `chmod 755 logs` |
| 8 | `run_*.json` 最近 7 天成功率 ≥80% | `近 7 天失败率高于 20%,跑 doctor --verbose` |
| 9 | 网络可达性(可选,不阻塞):`api.ark.cn-beijing.volces.com` | `检查网络/代理设置` |

## 落地步骤

1. **`doctor.py`** 实现 `check_<name>()` 系列函数,每个返回 `(status, message)`,status ∈ {ok, warn, fail}
2. **主流程**:`run_all_checks()` 依次跑 9 项,输出 emoji + 消息,聚合总评
3. **退出码**:全部 ok → 0;有 fail → 1;仅 warn → 0
4. **CLI 注册**:`python main.py doctor [--strict] [--json]`
5. **测试**(≥6 个):
   - 全 ok 健全环境 mock → 退出码 0
   - 缺 playwright → fail,提示安装
   - 缺 .env key → fail,提示复制
   - 仅缺一组 LLM → warn,退出码 0
   - 7 天无产出 → warn
   - JSON 输出模式结构正确
6. **commit**:`feat(T-A3): one-line doctor health check`

## 验收清单

- [ ] `python main.py doctor` 健全环境全部 ✅,退出码 0
- [ ] 缺 playwright → fail + 提示命令,退出码 1
- [ ] 缺 key → fail + 提示 .env 路径,退出码 1
- [ ] `--json` 输出可解析
- [ ] pytest 全绿(123 + ≥6 个)
- [ ] 使用实操文档.md 有 doctor 章节
- [ ] 架构评审与优化计划.md 追加批次
- [ ] commit 信息:`feat(T-A3): one-line doctor health check`
- [ ] log 完整

## 禁止项

- 不要引入新依赖(用标准库 `platform`、`os`、`shutil`、`urllib.request` 等)
- 不要碰 data/reports 历史日报
- 不要自动 push

## 失败处理

- 验收不过 → log 留痕,不 commit

## 完成后输出

```
=== T-A3 Report ===
diff stat: ...
pytest 末 30 行: ...
commit hash: ...
总结: <1 句话>
```
