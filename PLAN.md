# StudyOnPC 架构（短）

## 定位

Windows 个人/家庭「先学再看」：盯 Chrome 前台 YouTube，用**解锁时长余额**控制观看；余额耗尽或每日上限到达时，全屏题组答题，达标后解锁分钟。

**原创实现**。产品规则思路借鉴开源项目 [StudyOnTV](https://github.com/chadyi/StudyOnTV)（其许可证为 Personal Use Only），**不复制其源码**，也不打包其 APK。Windows 侧前台检测 / 静音 / PIN / 看门狗沿用并升级自本机既有 `youtube-grade1-quiz`。

## 模块

| 模块 | 职责 |
|------|------|
| `studyonpc/rules.py` | 余额消耗、每日上限、题组及格、连错补题、解锁发放 |
| `studyonpc/bank.py` | 题库加载；grade1 + StudyOnTV-like 字段归一化 |
| `studyonpc/state.py` | `data/state.json` 持久化与按本地日切 |
| `studyonpc/win_yt.py` | Win32 前台/枚窗/最小化；`set_mute.ps1`；Linux stub |
| `studyonpc/pinyin_ui.py` | 汉字自动拼音（ruby 标注） |
| `studyonpc/quiz_ui.py` | 童趣全屏题组 UI + 拼音 |
| `studyonpc/admin_server.py` | `0.0.0.0:8099` 状态页 + 家长管理 API |
| `studyonpc/watchdog.py` | 主进程 ↔ 看门狗互拉 |
| `studyonpc/app.py` | 主循环、整合上述模块 |
| `studyonpc.py` | 入口：`--role=main\|watchdog`、`--once`、`--force` |

## 数据流

1. 轮询（默认 2.5s）：前台标题含 youtube 关键词且可看 → 扣余额、加今日已用。
2. 不可看且前台是 YouTube（或管理端强制 / `--once`）→ 静音 + 最小化 YT → 题组。
3. 题组：`questions_per_set + pending_extra`；正确数 ≥ `ceil(n * pass_ratio)` → 发放 `min(unlock, 今日剩余额度)`，清补题。
4. 未达标 → 立刻再来一组（仍保持静音/最小化）。
5. LAN 管理改规则/导题库/强制出题/PIN 退出。

## MVP 不做

间隔重复、星星奖励、主观题 AI 批改、YouTube 以外的整机应用锁、Android TV 端。
