# 项目设计蓝图 · spine-forge

> **这份文件回答一个问题：这个项目最终要长成什么样。**
>
> 与 `PROJECT_LOG.md` 的分工：
> - `PROJECT_LOG.md` = **过去**：做过什么、踩过什么坑、当前状态
> - `PROJECT_BLUEPRINT.md` = **未来**：要做哪些模块、每个模块负责什么、边界在哪
>
> 改代码前先看这里，确认新代码属于哪个模块。**不属于任何模块的代码，多半不该写。**

---

## 一、产品一句话

**把现成的 Spine 骨架换一副皮，输出能直接在 Spine 编辑器继续编辑的工程。**

典型场景：猫头鹰 → 鸽子。骨骼、动画、动作全部复用，只换外形和身形比例。

---

## 二、模块总览

一个模块 = 一个职责 = 一个目录。**目录边界就是职责边界**，跨边界调用必须走公开接口。

```
src/spine_forge/
│
├── core/           【地基】数据模型，零第三方依赖
├── assets/         【像素与文件】图集、图像、磁盘
├── reskin/         【业务】换皮算法（纯函数，无 IO、无 HTTP）
├── workspace/      【状态】会话、工作区、撤销
├── server/         【传输】HTTP 接口，无业务逻辑
├── exporter/       【交付】打包成 Spine 可打开的工程
└── cli.py          【入口】命令行
web/                【界面】浏览器前端

tests/              【保障】每个模块一份
```

**依赖方向是单向的，不许反向**：

```
cli ──► server ──► workspace ──► reskin ──► assets ──► core
                                  │
                                  └──► exporter ──► assets
```

`core` 不知道 `assets` 存在；`reskin` 不知道 HTTP 存在；`server` 不知道 Pillow 存在。
**违反这条就是架构腐化的开始。**

---

## 三、模块规格

下面每个模块列出：定位、公开接口、内部结构、明确不做什么、验收标准。

---

### 模块 1 · `core/` — 数据模型

**定位**：Spine 骨架的内存表示。零第三方依赖，可脱离一切外部库测试。

**为什么零依赖**：序列化是最容易静默出错的地方，必须能独立验证。

| 文件 | 职责 | 状态 |
|---|---|---|
| `core/rig.py` | rig 文档：骨骼/槽位/皮肤/附件/约束 | ✅ 已有 |
| `core/model.py` | 早期数据模型 | ✅ 已有（线 A） |
| `core/serializer.py` | Spine JSON 序列化 | ✅ 已有（线 A） |

**公开接口**（`rig.py`）：
```python
Rig.load(path) / .save(path) / .copy()
.bones / .bone(name) / .children_of(b) / .descendants(b)
.slots / .slot(name) / .slots_on_bone(b)
.attachment_table(skin) / .attachment(slot, name, skin)
.constraints / .constraints_on_bone(b)
.summary()
```

**不做**：不读图、不碰像素、不发请求、不写业务规则。

**验收**：`pytest tests/test_rig.py` 全绿，覆盖加载/子树/附件查找。

---

### 模块 2 · `assets/` — 图集与图像

**定位**：一切"数据落在磁盘上"和"像素"的事。分两个互不依赖的文件。

| 文件 | 职责 | 依赖 | 状态 |
|---|---|---|---|
| `assets/atlas.py` | `.atlas` 文本解析/序列化 | **零依赖** | ✅ 已有 |
| `assets/images.py` | 切图、追加区域、扩容 | Pillow | ✅ 已有 |

**为什么拆开**：`atlas.py` 是纯字符串处理，能毫秒级测试；`images.py` 需要 Pillow，慢。
混在一起会让格式测试也背上图像依赖。

**公开接口**：
```python
# atlas.py
parse(text) / dumps(atlas) / load(path) / save(atlas, path)
Atlas.find_region(name) / .region_names()
Page.find(name)
Region.position / .size

# images.py
load_page_image(atlas_path, page)
cut_region(image, region)
next_free_y(page)
append_to_page(page_image, page, name, sprite, padding)
grow_page(page_image, page, extra, size)
save_page_image(image, atlas_path, page)
```

**不做**：不理解骨骼，不做缩放决策，不发请求。

**验收**：`test_atlas.py` 往返无损；`test_images.py` 处理 rotate 区域正确。

---

### 模块 3 · `reskin/` — 换皮算法 ⭐ 核心

**定位**：纯算法层。**输入数据结构，输出数据结构**。不读盘、不写盘、不碰 HTTP。

这是整个项目最值钱的部分，也是最需要测试覆盖的部分。

| 文件 | 职责 | 状态 |
|---|---|---|
| `reskin/align.py` | 算比例：新图该缩放多少 | ✅ 已有 |
| `reskin/propagate.py` | 联动：子骨骼/子附件跟着调 | ✅ 已有 |
| `reskin/replace.py` | 编排：串起上面两步 | ✅ 已有 |

**公开接口**：
```python
# align.py
compute_scale(source_img, target_img, mode, manual, source_scale) -> AlignResult

# propagate.py
propagate_scale(rig, slot, bone, factor, skin, include_children) -> PropagationReport

# replace.py
apply_reskin(rig, atlas, page_image, slot=, new_image=, ...) -> ReskinResult
```

**核心规则（写进代码注释了，这里再记一遍）**：

| 对象 | 缩放什么 | 不缩什么 | 原因 |
|---|---|---|---|
| 骨骼 | `x` `y` `length` | `rotation` | 旋转是角度 |
| 区域附件 | `x` `y` | `width` `height` | 尺寸是采样框，缩了会二次缩放 |
| mesh 顶点 | **仅 x/y** | 索引、权重、N | 变长格式，索引不能乘 |
| 图集换算 | —— | —— | 必须 `/ page.scale` |

**不做**：不写文件，不生成图集 PNG（交给 `assets/images.py`），不理解 HTTP。

**验收**：`test_align.py` / `test_propagate.py` / `test_replace.py`。

---

### 模块 4 · `workspace/` — 会话与状态 🆕 待建

**定位**：一个"正在编辑的工程"的内存态。前端每开一个角色就是一个 workspace。

**为什么单独一个模块**：换皮是**有状态的**交互过程 —— 换头 → 看效果 → 微调 → 再换眼睛。
这些状态既不属于算法（算法是纯函数），也不属于 HTTP（HTTP 无状态）。
硬塞进任何一边都会烂。

| 文件 | 职责 |
|---|---|
| `workspace/session.py` | 一个编辑会话：rig + atlas + 页图 + 变更历史 |
| `workspace/history.py` | 撤销/重做栈 |
| `workspace/registry.py` | 会话 id → session 的映射，生命周期管理 |

**公开接口**：
```python
Workspace.open(rig_path, atlas_path)     # 从磁盘开一个工程
ws.reskin(slot, image, **opts)           # 执行一次换皮，进历史
ws.undo() / ws.redo()
ws.snapshot()                            # 给前端的状态摘要
ws.export(out_dir)                       # 委托给 exporter
ws.close()
```

**不做**：不做 HTTP 路由，不做图像算法，不决定 UI 长什么样。

**边界原则**：`workspace` 可以调 `reskin` 和 `exporter`；
但 `reskin` **绝不能**反过来调 `workspace`。

**验收**：`test_workspace.py` —— 连续换 3 个部件后能撤销到任意一步。

---

### 模块 5 · `server/` — HTTP 层 🆕 待建

**定位**：只做传输。**薄到能一眼看完**。任何业务逻辑出现在这里都是错的。

| 文件 | 职责 |
|---|---|
| `server/app.py` | 应用装配、静态托管 |
| `server/routes.py` | 路由表 |
| `server/schemas.py` | 请求/响应结构 |

**接口设计（草案）**：

| 方法 | 路径 | 作用 |
|---|---|---|
| `POST` | `/api/session` | 开一个工程，返回 session_id + 摘要 |
| `GET` | `/api/session/{id}` | 取当前状态 |
| `GET` | `/api/session/{id}/parts` | 部件列表（给右栏用） |
| `POST` | `/api/session/{id}/reskin` | 换一个部件，返回新图集 + 报告 |
| `POST` | `/api/session/{id}/undo` | 撤销 |
| `POST` | `/api/session/{id}/export` | 导出到目录 |
| `GET` | `/api/session/{id}/atlas.png` | 当前图集页（前端刷新贴图用） |

**返回给前端的数据形状**（关键，决定热重载能不能做）：
```json
{
  "ok": true,
  "scale": 0.985,
  "region": "head-base_reskin",
  "atlas_url": "/api/session/abc/atlas.png?v=7",
  "uv": {"u": 0.0, "v": 0.75, "u2": 0.58, "v2": 1.0},
  "report": { "bones_scaled": [...], "attachments_scaled": [...] }
}
```

**不做**：不碰 Pillow，不碰 reskin 算法，不管理会话生命周期（那是 workspace 的事）。

**验收**：`test_server.py` 用 FastAPI TestClient 跑通全流程。

---

### 模块 6 · `exporter/` — 导出 🆕 待建

**定位**：把内存里的工程写成**Spine 编辑器能直接打开**的目录。

目前 `reskin/export.py` 里有个 1KB 的小函数，等导出需求变复杂（多页图集、打包 zip、生成预览 HTML）时升级成独立模块。

| 规划 | 职责 |
|---|---|
| `exporter/project.py` | 写 json + atlas + png |
| `exporter/bundle.py` | 打包成 zip |
| `exporter/preview.py` | 生成自包含预览 HTML |

**不做**：不做算法，不管理状态。

**验收**：导出的目录丢进 Spine 编辑器能打开且动画正常。

---

### 模块 7 · `web/` — 前端 🆕 待建

**定位**：浏览器里的三栏工作台。

```
┌──────────────────────────────────────────────────┐
│  工具栏：[打开工程] [导出]          状态：已换 3 处 │
├────────────────────────┬─────────────────────────┤
│                        │  部件列表                │
│   实时渲染              │  ├ 头 ●                  │
│   (spine-player)       │  ├ 身体                  │
│                        │  ├ 翅膀 L / R            │
│                        │  └ 叶子 ×7               │
│                        │  ── 选中：头 ──          │
│                        │  [上传新图]              │
│                        │  比例 0.985 (自动)       │
│                        │  [应用] [撤销] [重置]     │
├────────────────────────┴─────────────────────────┤
│  动画：idle | blink | left | right | up | down   │
└──────────────────────────────────────────────────┘
```

| 文件 | 职责 |
|---|---|
| `web/index.html` | 骨架布局 |
| `web/js/app.js` | 主控：装配各部分 |
| `web/js/player.js` | 封装 spine-player，暴露换贴图接口 |
| `web/js/panels.js` | 部件列表、属性面板 |
| `web/js/api.js` | 所有 fetch 集中在这里 |
| `web/css/style.css` | 样式 |

**约束**：`player.js` 之外的地方**不许**直接碰 `spine.*` 对象。

**关键能力（热重载）**：
```js
// 不刷新、不重载，直接换
player.swapTexture(atlasUrl, {forceReload: true});
player.setRegionUV(slotName, uv);
```

**验收**：上传新图 → 界面立刻变化，无刷新。

---

## 四、数据流（完整一次换皮）

```
[用户] 点击"头" → 上传鸽子头.png
   │
   ▼ web/js/api.js
POST /api/session/{id}/reskin  {slot, image}
   │
   ▼ server/routes.py
workspace.reskin(slot, image)
   │
   ├─► reskin/align.py      算比例 0.985（含 page.scale 补偿）
   ├─► assets/images.py     追加新区域到页图，必要时扩容
   ├─► reskin/propagate.py  联动子骨骼/子附件/子网格
   └─► workspace/history.py 压入撤销栈
   │
   ▼ 返回 {scale, atlas_url, uv, report}
[前端] player.setTexture(newAtlas) + player.setRegionUV(...)
   │
   ▼ 屏幕
[立刻看到鸽子头]
   │
   ▼ 用户满意 → 点"导出"
workspace.export(out_dir) → exporter/project.py → 磁盘
```

**每一段都能单独测**，这就是为什么切这么多模块。

---

## 五、扩展点（以后要加的功能，留好位置）

按预期价值排序。**加功能只需新增文件/新增模块，不改已有模块。**

| 功能 | 加在哪 | 怎么接 |
|---|---|---|
| **AI 生成新部件图** | 新增 `reskin/generator.py` | `workspace.reskin(slot, image=None, prompt="鸽子头")` |
| **批量换整套皮** | 新增 `reskin/batch.py` | 循环调 `apply_reskin`，共用一次图集合成 |
| **多图集页支持** | 扩展 `assets/images.py` | 页满时自动开新页 |
| **导出为 Spine 4.x 各种版本** | `exporter/` 内新增版本适配器 | 按 `skeleton.spine` 字段分流 |
| **复用动画到新骨架（retarget）** | 新增 `reskin/retarget.py` | 骨骼名映射表 + 动画重采样 |
| **动作编辑** | 新增 `editor/` 整个模块 | 独立线，和换皮并列 |
| **部件级色彩重映射** | `reskin/recolor.py` | 只改 RGBA，不碰几何（最安全的换皮） |
| **预览/对比截图** | `exporter/preview.py` | 前后对比图 |
| **CLI 批处理** | `cli.py` 加子命令 | 无状态，文件进文件出 |

**原则**：新功能优先做成**新文件**，而不是往老文件里塞 `if`。
一个文件超过 400 行就该考虑拆。

---

## 六、明确的非目标

这些**不做**，避免范围失控：

| 不做 | 原因 |
|---|---|
| 完整的 Spine 编辑器 | 官方编辑器已经很完整，我们只做换皮 |
| 从零画骨骼 | 线 A 已经覆盖，不在这条线里 |
| 网格重建（重新三角化） | 复杂度高，第一期保留原网格 |
| 云端服务 | 本地工具，不需要账号和多租户 |
| 实时协作 | 无此需求 |
| 内置素材库 | 用户自己提供图 |

---

## 七、质量门槛

每加一个模块，必须同时满足：

1. **有测试** —— `tests/test_<模块>.py`，覆盖公开接口
2. **有文档** —— 在 `PROJECT_LOG.md` 追加一节
3. **有边界** —— 明确写"这个模块不做什么"
4. **依赖单向** —— 违反依赖图直接拒绝合并

**回归测试必须钉住的 4 条**（都是真实崩溃过的）：

```
test_atlas_roundtrip        往返无损
test_empty_slot_rejected    空槽位拒绝换皮
test_mesh_stride            变长顶点不破坏骨骼索引
test_atlas_scale_compensation  scale 0.5 图集补偿正确
```

---

## 八、目录终态

```
spine-forge/
├── PROJECT_LOG.md          过去：做了什么、踩了什么坑
├── PROJECT_BLUEPRINT.md    未来：要做什么、怎么分模块  ← 本文件
├── README.md               怎么用
├── pyproject.toml
│
├── src/spine_forge/
│   ├── core/               地基，零依赖
│   ├── assets/             图集与图像
│   ├── reskin/             换皮算法 ⭐
│   ├── workspace/          会话与状态      🆕
│   ├── server/             HTTP 层         🆕
│   ├── exporter/           导出打包        🆕
│   ├── splitter/           拆图（线 A）
│   ├── stages/             流水线（线 A）
│   └── cli.py              命令行入口
│
├── web/                    前端工作台      🆕
│   ├── index.html
│   ├── js/
│   └── css/
│
├── tests/                  每个模块一份
├── tools/                  排查脚手架（非产品代码）
├── viewer/                 验证页面（非产品代码）
└── examples/               示例数据
```

---

## 九、实现顺序（渐进，一次一件事）

每步**独立可验收**，做完再开下一步。**不跨步。**

| 步 | 内容 | 产出 | 验收方式 |
|---|---|---|---|
| 1 | 单元测试 | `tests/` 覆盖已有 3 个模块 | `pytest` 全绿 |
| 2 | 修 5px 偏移 | `assets/images.py` 小改 | 前后对比图零偏移 |
| 3 | `workspace/` | 会话 + 撤销 | 连续换 3 处可撤销 |
| 4 | `exporter/` 独立 | 从 `reskin/export.py` 升级 | 导出目录能被 Spine 打开 |
| 5 | `server/` 最小 | 4 个接口 | curl 跑通全流程 |
| 6 | `web/` 三栏 | 可点选、可上传 | 浏览器里换一个部件 |
| 7 | 热重载 | 不刷新换贴图 | 上传后立刻变化 |
| 8 | AI 生成 | `reskin/generator.py` | 输入提示词出新图并自动换 |

**第 1、2 步是清债，必须最先做。** 带着 bug 往下建，后面每一步都在错地基上盖楼。

---

## 十、给后来者的话

1. **先读这份文件，再读 `PROJECT_LOG.md`** —— 一个说往哪走，一个说走过哪
2. **新代码先找归属模块** —— 找不到归属，就是设计没想清楚
3. **崩了先二分** —— `viewer/bisect.js`，别猜
4. **改 `reskin/` 前先跑 `tools/inspect_stride.py`** —— 顶点格式是变长的
5. **图集先看 `scale`** —— 半分辨率打包是默认陷阱
6. **一次只推进一步** —— 步子大了，出问题定位不到

---

_创建：2026-11-07 · 模块化蓝图 v1_
