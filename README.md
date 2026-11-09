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
| `split` | 一张图（`--splitter alpha` 透明底 / `--splitter colour` 平涂插画） | `parts/*.png` + `parts.json` + `preview/` |
| `skeleton` | 带手标关节的图 + 关节表 | `bones.json` + `skeleton_panel.png` + `marks.json` |
| `rig` | `parts.json` | `rig.json`（**可编辑**） |
| `build` | `rig.json` | `skeleton.json` + `.atlas` + 图集页 |
| `preview` | `rig.json` 或 `skeleton.json` | 自包含的 `.html` |

`preview` 两种输入都收：草稿阶段看 `rig.json`，构建后看 `skeleton.json`。

### 平涂插画拆分（colour splitter）

平涂图按**填色**拆件（不是按透明度），完整流程与全部坑点见
**[docs/parts-splitting.md](docs/parts-splitting.md)**。

```bash
python -m spine_forge.cli split character.png --out out --splitter colour
# parts: 11 / coverage: 0.935 / mean_diff: 25.24
```

输出 `parts/`（每张都是原始画布尺寸、全画布对齐）、`preview/parts_sheet.png`（人工验收拼版）、
`preview/reassembly.png`（原图 vs 重组对照）。`--no-preview` 可跳过预览。

### 手标关节 → 骨架（skeleton）

人在原图上用**空心圈**标出关节，工具读出圈的位置、生成 Spine 骨、并把骨架画回原图上供复核。
完整流程与限制见 **[docs/skeleton-from-marks.md](docs/skeleton-from-marks.md)**。

```bash
python -m spine_forge.cli skeleton art.png --out out \
    --marks art_marks.png --joints joints.json --name girl
# marks: 20 / bones: 20 / panel: out/skeleton_panel.png
```

交付物是 `skeleton_panel.png`（骨架 1:1 画在原图上 + 右侧坐标表）和 `bones.json`
（关节 + Spine 局部变换 + 约束）。`--joints` 可省略，此时只输出读到的标记供确认。

`joints.json` 可带 `constraints`：默认 4 个 IK（双脚双脚腕）+ 2 个 transform 跟随（头、头发），
字段与官方示例一致，详见 [docs/skeleton-from-marks.md](docs/skeleton-from-marks.md)。

### 部件挂到骨上（assemble）

```bash
# ① Spine 编辑器：散图模式（不需要 atlas）
python -m spine_forge.cli assemble parts.json --bones rig/bones.json \
    --out examples/girl/spine-images --name girl --mode images

# ② 游戏/网页运行时：图集模式
python -m spine_forge.cli assemble parts.json --bones rig/bones.json \
    --out examples/girl/dist --name girl --mode atlas
```

两种模式写出的骨/槽/附件数值**完全一致**，只差图从哪来：

| 模式 | 产物 | 用在 |
|---|---|---|
| `images` | `girl.json` + `images/*.png`（每件一张） | **Spine 编辑器** |
| `atlas` | `girl.json` + `girl.atlas` + `girl.png` | 运行时（spine-player / 引擎） |

> 实测：部分 Spine 安装读不了本工具生成的图集，但散图模式能直接打开；
> 遇到“图片渲染不出来”先用 `--mode images` 排除图集问题。

#### 自检：`check`（结构错了当场报，不用等截图）

```bash
python -m spine_forge.cli check examples/girl/dist-warp/girl.json
```

查：骨/槽名重复与引用、mesh 的 uvs 是否图内 0..1、权重是否归一、骨索引/三角形索引越界、
IK 目标是否存在。`assemble` 写完会自动跑一遍，不过直接报错。

> 所有已经踩过的坑（权重、uv、hull、IK 符号、约束抢骨、坐标系）见
> **[docs/spine-pitfalls.md](docs/spine-pitfalls.md)** —— 每条都写了“现象/根因/规则/谁在守”。

#### 会弯的腿：`--warp legs`（整图蒙皮，不是切两半）

```bash
python -m spine_forge.cli assemble parts.json --bones rig/bones.json \
    --out examples/girl/dist-warp --name girl --mode atlas --warp legs
```

默认 `--warp none`：腿是膝部切开的 `leg-*-up` / `leg-*-down` 两块**刚性**图片，各绑一根骨。
刚性图片不可能形变，膝盖一弯就是两半分开的“撕裂”缺口（`examples/girl/compare-knee-warp.png` 左）。

`--warp legs`：把两块按 alpha 重新拼回**整条腿**，发一个 Spine **mesh（蒙皮网格）**，
顶点沿「髂→膝→踝」这条骨链取最近点，再按弧长加权到 `leg_*` + `shin_*` 两根骨
（关节两侧各有约 10px 的过渡带）。
弯膝＝整张图在关节处被**扭曲变形**，没有接缝、没有缺口（对比图右侧）。

> 权重必须用**整条骨链的最近点**算，不能只投影到小腿轴线：贴图框的角离膝盖 80px，
> 投影却会落进过渡带，被分给小腿 → 拖膝盖时大腿被拽成一块苍白的大弯月。

两条静默坑（写错了不报错、只是图错）：

1. **权重顶点不是 x,y 对**：`vertices` = 每顶点 `boneCount` + `boneCount × (骨索引, x, y, 权重)`，
   且 x/y 是**同一个世界点在各自骨骼局部坐标系**里的坐标。
2. **mesh 的 uvs 是“图内 0..1”，不是图集绝对坐标**（运行时会用 region 的 bounds 再换算），
   且 `v=0` 在图**上沿**（图集 y 向下）。

---

## 工程结构

```
src/spine_forge/
├── core/          零依赖：数据模型 + Spine 4.2 序列化 + verify（结构自检）
├── splitter/      拆图（可替换接口）—— alpha：连通域；colour：填色分族 + 文档 docs/parts-splitting.md
├── rig/           手标关节 → 骨架：markers（读圈）+ skeleton（局部变换）+ overlay（审阅图）
│                  mesh（整图蒙皮：权重网格，膝盖弯曲用）
├── stages/        split / skeleton / assemble / rig / build / preview，各自读写文件
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

