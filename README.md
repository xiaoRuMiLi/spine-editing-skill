# Spine Forge

一张图 → 部件图 → 骨骼 → 可直接在 Spine 编辑器打开的工程。

**产品形态**：AI 通过命令行逐条调用，人通过修改 JSON 介入。没有会话状态，每一步都是文件进、文件出。

---

## 流水线

```
character.png
    │  split      （拆部件，产 parts.json）
    ▼
parts/*.png + parts.json
    │  rig        （推骨骼树，产 rig.json ← 人可以改这个）
    ▼
rig.json
    │  build      （产 Spine 工程）
    ▼
skeleton.json + *.atlas + *.png
    │  preview    （产 HTML，快速看效果）
    ▼
preview.html
```

**核心**：`rig.json` 是唯一可编辑的中间产物。AI 生成初稿，人改数字，再 `build` 重出。`skeleton.json` 是派生物，任何时候都能重新生成。

---

## 快速开始

需要 Python 3.10+、Pillow、numpy。

```bash
# 在项目根目录
set PYTHONPATH=src          # Windows (cmd)
# export PYTHONPATH=src     # bash

python examples/make_fixture.py --out examples/sample_character/character.png

python -m spine_forge.cli split   examples/sample_character/character.png --out examples/sample_character/out
python -m spine_forge.cli rig     examples/sample_character/out/parts.json --out examples/sample_character/out/rig.json --name hero
python -m spine_forge.cli build   examples/sample_character/out/rig.json --out examples/sample_character/out/dist
python -m spine_forge.cli preview examples/sample_character/out/dist/skeleton.json --out examples/sample_character/out/preview.html
```

从示例导出的产物，用 Spine 编辑器直接打开 `examples/sample_character/out/dist/skeleton.json`。

### AI 调用时加 `--json`

```bash
python -m spine_forge.cli split image.png --out out --json
# {"ok": true, "parts": 5, "manifest": "out\\parts.json", "parts_dir": "out\\parts"}
```

失败时退出码为 1，且 `--json` 下输出 `{"ok": false, "error": "..."}`。

---

## 命令

| 命令 | 输入 | 输出 |
|---|---|---|
| `split` | 一张带透明背景的图 | `parts/*.png` + `parts.json` |
| `rig` | `parts.json` | `rig.json`（**可编辑**） |
| `build` | `rig.json` | `skeleton.json` + `.atlas` + 图集页 |
| `preview` | `rig.json` 或 `skeleton.json` | 自包含的 `.html` |

`preview` 两种输入都收：草稿阶段看 `rig.json`，构建后看 `skeleton.json`。

---

## 工程结构

```
src/spine_forge/
├── core/          零依赖：数据模型 + Spine 4.2 序列化
├── splitter/      拆图（可替换接口）—— v1 是连通域
├── stages/        split / rig / build / preview，各自读写文件
└── cli.py         命令入口

tests/             测试
examples/          示例与夹具生成
```

`core` 零第三方依赖是刻意的：序列化是最容易出错的部分，必须能脱离 Pillow/numpy 单独测试。

---

## 已知边界

**v1 的拆图是连通域切分（无 AI、无 API key）。**

- ✅ 能拆：彼此分离的部件（PSD 分层导出的 PNG、拼接素材）
- ❌ 不能拆：连成一片的人体（上臂和小臂在图上连通，就是一个色块）
- ❌ 不认识语义：部件名是 `part_01`，不是 `左大臂`

**所以第一版验证的是管道，不是效果。** 拿连体人物图喂进去会切得很难看——那是预期行为，不是 bug。

**还没有的能力**（按优先级）：

1. mesh / 权重（平滑变形）—— 目前只有 region 附件，绑定是刚性的
2. 语义拆分（SAM / GroundingDINO）—— 替换 `splitter/`
3. ik / transform / path 约束
4. slot、deform、drawOrder 时间轴
5. 动画生成

---

## Spine 4.2 格式的坑

序列化在 `core/serializer.py`，这几个细节会让文件**静默失效**：

| 坑 | 表现 | 正确做法 |
|---|---|---|
| 旋转用 `angle` | 动画在跑但什么都不转 | 4.x 用 `value` |
| 曲线只给 4 个数 | 角色渲染一帧就消失（NaN 扩散） | `translate/scale/shear` 需要 8 个数 |
| 曲线用归一化值 | 插值位置错乱 | 控制点是绝对坐标，同 time/value 单位 |
| 曲线挂在帧尾 | 缓动整体错位一帧 | 曲线作用于从该帧**开始**的区段 |
| `skeleton.x` 漏写 | 角色整体右偏半个宽度 | `x = -width/2` |

另外附件是嵌套两层：`skins[0].attachments[slot名][附件名]`，不是一层。

---

## 许可

本项目为原创实现。格式知识来自 Spine 官方文档与 runtime 行为，未复制任何第三方代码。
