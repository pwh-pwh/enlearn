# enlearn

一个本地优先的英语单词学习记忆 TUI/CLI。它可以从网络开源词库导入四六级、雅思、托福、GRE 等类别的单词，并用简化 SM-2 算法安排复习。

## 功能

- 默认启动终端 TUI，支持菜单式操作。
- 从 ECDICT 词库按类别全量导入单词，远程词库下载后会缓存在本地；已经导入过的词库会直接提示已导入。
- 本地 SQLite 保存词库和复习进度。
- 支持手动添加单词。
- 支持到期复习、评分、下次复习日期计算。
- 支持设置每天学习的单词数量、当前学习词库和是否乱序复习，默认每天 50 个、词库 `cet4`、到期顺序。
- 支持今日任务页、每 10 个一组学习、错词强化和熟词跳过。
- 支持学习进度统计：已掌握、学习中、未学习、错词/薄弱。
- 支持查看单词列表和学习统计。

## 使用

直接运行：

```bash
python main.py
python main.py tui
python main.py categories
python main.py fetch
python main.py review
python main.py stats
python main.py config
```

TUI 操作：

- `↑/↓` 或 `j/k`：移动菜单和列表。
- `Enter`：确认。
- `q` 或 `Esc`：返回或退出。
- 复习时先回忆释义，按 `Enter` 看答案，再按 `0-5` 评分。
- 今日任务按 10 个单词一组推进，组内低分词会立即进入错词强化。

如果通过 uv 安装当前项目，也可以使用命令入口：

```bash
uv run enlearn categories
uv run enlearn fetch --category ielts
uv run enlearn review
```

## 常用命令

```bash
# 启动 TUI
python main.py
python main.py tui

# 查看支持的词库类别
python main.py categories

# 从网络词库导入当前学习词库
python main.py fetch

# 指定词库全量导入；远程 CSV 已缓存时不会重复下载
python main.py fetch --category cet4

# 未导入该词库时，强制重新下载远程词库缓存
python main.py fetch --category cet6 --refresh

# 手动添加单词
python main.py add hello --translation 你好 --phonetic "həˈləʊ"

# 查看已导入单词
python main.py list --limit 20
python main.py list --category cet4 --limit 20

# 复习今天到期的单词
python main.py review
python main.py review --limit 20

# 查看或修改每天学习数量
python main.py config
python main.py config --daily-limit 80
python main.py config --category ielts
python main.py config --daily-limit 80 --category ielts
python main.py config --random-order on
python main.py review --random
python main.py review --ordered

# 查看学习统计
python main.py stats
```

## 数据位置

运行后会在项目目录生成 `.enlearn/`：

- `.enlearn/enlearn.db`：SQLite 数据库。
- `.enlearn/cache/ecdict.csv`：远程词库缓存。

## 词库来源

默认使用 ECDICT：<https://github.com/skywind3000/ECDICT>

ECDICT 是 MIT 许可的英汉词典数据集，包含单词、音标、中文释义、英文释义、词性、考试标签和词频等字段。
