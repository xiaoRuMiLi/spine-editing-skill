# 项目进度台账 · spine-forge

> 这份文件只做一件事：**记录项目里有什么、谁负责什么、改过什么**。
> 每次有实质改动就追加一节，不要事后补写。
> 代码变了而这里没变，就是台账失效 —— 下次谁都修不动。

---

## 一、两条线，别混

项目里有**两条互不相干的线**，各自独立演进。混淆这两条线会让后续判断全错。

| 线 | 目录 | 输入 | 输出 | 状态 |
|---|---|---|---|---|
| **A. 从零生成骨架** | `src/spine_forge/{core,splitter,stages}` | 一张角色图 | skeleton.json + atlas | 已有（阶段1） |
| **B. 换皮（reskin）** | `src/spine_forge/{core,assets,reskin}` | 现成 rig + 新部件图 | 新 rig + 新图集 | **本次新增，已跑通** |

两条线共用 `core/`，但 B 线**不复用** `splitter/` 和 `stages/`。
B 线的输入是**已经存在的 Spine 工程**，不是一张整图。

---

## 二、B 线（换皮）：本次会话新建的东西

### 目标

把已有 rig（例：猫头鹰）的某个部件换成新图（例：鸽子头），并让骨骼、子部件、网格跟着等比调整，产出能直接在 Spine 编辑器打开的新工程。

### 包结构

```
src/spine_forge/
├── core/rig.py        ← 本次新增
├── assets/            ← 本次新增（整个包）
│   ├── atlas.py
│   ├── images.py
│   └── __init__.py
└── reskin/            ← 本次新增（整个包）
    ├── align.py
    ├── propagate.py
    ├── replace.py
    ├── export.py
    └── __init__.py
```

### 逐文件说明

#### `core/rig.py` — rig 文档模型（6.8K）

**职责**：只做数据结构，不碰像素。加载/保存 `.json` 骨架，提供骨骼树、槽位、皮肤、附件、约束的查询。

| 成员 | 作用 |
|---|---|
| `Rig.load(path)` / `.save(path)` | 读写骨架 JSON |
| `.copy()` | 深拷贝，改之前必须调，避免污染源 |
| `.bones` / `.bone(name)` / `.bone_names()` | 骨骼访问 |
| `.children_of(bone)` / `.descendants(bone)` | **联动核心**：取子树 |
| `.slots` / `.slot(name)` / `.slots_on_bone(bone)` | 槽位访问 |
| `.attachment_table(skin)` | 返回 `{slot: {名字: 附件}}`，注意是**嵌套两层** |
| `.attachment(slot, name, skin)` | 取单个附件 |
| `.constraints` / `.constraints_on_bone(bone)` | 约束访问 |
| `.summary()` | 给前端/日志用的摘要 |

**关键点**：`data` 字典原样保留，未知字段不丢。这是刻意的 —— 编辑器写的东西不能因为我们是新工具就吞掉。

---

#### `assets/atlas.py` — `.atlas` 文本解析（6.9K）

**职责**：纯文本解析，**零图像依赖**（可以脱离 Pillow 单独测试）。

| 成员 | 作用 |
|---|---|
| `parse(text)` / `dumps(atlas)` | 文本 ↔ 对象 |
| `load(path)` / `save(atlas, path)` | 文件读写 |
| `Atlas.find_region(name)` | 按名找 `(page, region)` |
| `Atlas.region_names()` | 所有区域名 |
| `Page.find(name)` | 页内查找 |
| `Region.position` / `.size` | 从 `bounds` 拆出的快捷属性 |

**真实格式**（4.3 实测，和旧版文档不同）：

```
owl.png
	size: 1024, 1024
	filter: Linear, Linear
	scale: 0.5              ← 半分辨率打包，极其重要
L_eye-closed
	bounds: 721, 342, 90, 86
L_foot
	bounds: 63, 316, 64, 48
	rotate: 90
```

- 缩进是语法本身：顶格 = 页名或区域名，缩进 = 属性
- 用 `bounds: x, y, w, h`，不是旧版的 `xy`/`size`/`orig`/`offset` 四件套
- `scale` 决定图集是几倍分辨率打包

---

#### `assets/images.py` — 图集像素操作（3.7K）

**职责**：所有涉及像素的事都在这，`atlas.py` 不碰图。

| 函数 | 作用 |
|---|---|
| `load_page_image(atlas_path, page)` | 打开页图，转 RGBA |
| `cut_region(image, region)` | 从页图切出某个区域，自动处理 `rotate` |
| `next_free_y(page)` | 现有内容的最低点（追加用） |
| `append_to_page(page_image, page, name, sprite, padding=2)` | **追加新区域**，不动老区域 |
| `grow_page(page_image, page, extra, size)` | 扩容到 2 的幂（Spine 对非 2 幂页的过滤不可靠） |
| `save_page_image(image, atlas_path, page)` | 落盘 |

**设计决策**：新区域**追加**而不是覆盖旧区域。
好处是其它 26 个部件完全不受影响；
代价是图集会膨胀（1024×1024 → 1024×2048）。

---

#### `reskin/align.py` — 比例推断（5.6K）

**职责**：算出"新图该缩放到多大"。这是整个换皮里最容易错的一步。

| 成员 | 作用 |
|---|---|
| `compute_scale(source, target, mode, manual, source_scale)` | 主函数 |
| `AlignResult.scale` | 最终倍率 |
| `AlignResult.source_box` / `.target_box` | 两边的**不透明**包围盒 |
| `AlignResult.source_size_in_rig_units` | 源尺寸换算回 rig 单位 |
| `_opaque_box(image)` | alpha > 8 的包围盒 |

**`mode` 的四个选项**：

| mode | 用于 |
|---|---|
| `height` | 头、躯干、四肢（默认） |
| `width` | 翅膀这类横向部件 |
| `area` | 形状差异大时最稳 |
| `fit` | 取两者较大值，保证不溢出 |

**⚠️ `source_scale` 参数是本次修复的核心**

`owl.atlas` 里 `scale: 0.5` —— 图集是半分辨率打包的。
从图集切出来的 303px，在 rig 坐标系里代表 606px。

不补偿的后果：
```
597(新图) / 303(图集像素)  = 1.97   ← 错
597(新图) / (303/0.5)      = 0.985  ← 对
```

1.97 会让整棵树放大一倍，眼睛飞出头部。**这就是第二节里"头部失真"的真因。**

---

#### `reskin/propagate.py` — 联动修改（8.0K）

**职责**：换了一个部件后，把挂在它下面的东西全部按同一比例调整。

| 成员 | 作用 |
|---|---|
| `propagate_scale(rig, slot, bone, factor, skin, include_children)` | 主函数 |
| `PropagationReport` | 改了什么，跳过什么 |
| `_parse_vertices(vertices)` | **解析变长顶点格式** |
| `_scale_vertices(attachment, factor)` | 只缩放 x/y |
| `_scale_entry(entry, keys, factor)` | 按 key 缩放 |

**缩放清单**：

| 对象 | 缩放键 | 说明 |
|---|---|---|
| 骨骼 | `x`, `y`, `length` | 旋转是角度，**不能缩** |
| 区域附件 | `x`, `y` | 相对骨骼的偏移 |
| mesh 顶点 | **仅 x/y** | 见下 |
| 附件 `width`/`height` | **不缩** | 是采样框，缩了会二次缩放 |

**⚠️ mesh 顶点是变长格式（本次最深的坑）**

不是 `x,y` 配对，是：

```
[骨骼数 N] [索引][x][y][权重] × N     ← 每个顶点
```

实测 `beak`：105 个数 / 13 个 UV 对 = 9 个数/顶点（N=2 时 `1 + 2×4 = 9`）。

固定 stride 会**把骨骼索引 10 也乘上 1.97**，指向不存在的骨骼，运行时直接 `appliedPose` 崩溃。

正确做法：用 `_parse_vertices` 按 N 解析，只动每组里的 `x`/`y`，索引和权重原样保留。

---

#### `reskin/replace.py` — 换皮主流程（7.9K）

**职责**：串起"切旧图 → 算比例 → 合成新页 → 改 rig"。

| 成员 | 作用 |
|---|---|
| `apply_reskin(rig, atlas, page_image, slot=..., new_image=..., ...)` | 唯一入口 |
| `ReskinResult` | 新 rig + 新 atlas + 新页图 + 报告 |
| `.report()` | 给日志/前端的摘要 |

**执行顺序**：
1. 查槽位、找附件 —— **空槽位直接报错**（见下）
2. 切出旧图当基准
3. `compute_scale` 算倍率（含 atlas scale 补偿）
4. 追加新区域到页图（必要时扩容）
5. 改附件 `path` / `width` / `height`
6. `propagate_scale` 联动

**⚠️ 空槽位不能动**

```json
{"name": "R_eye-closed", "attachment": null}
```

`null` 表示这层当前是隐藏的。凭空给它造附件 → 槽位说"我没有"、皮肤里有 → 运行时崩溃。
现在直接抛错，让调用方知道要换就换可见的部件。

**⚠️ `width`/`height` 类型要跟原文件一致**

原文件是 `597.0`（float），就写 float；是 `597`（int）就写 int。
混用会让解析器出错。代码里用 `cast` 判断。

---

#### `reskin/export.py` — 落盘（1.0K）

| 函数 | 作用 |
|---|---|
| `write_project(out_dir, rig, atlas, page_image, name)` | 写 json + atlas + png，返回路径 |

刻意做得简单：**放哪里由调用方定，这里只负责摆好**。

---

## 三、验证工具（viewer/ 与 tools/）

这些不是产品代码，是**排查用的脚手架**，别当正式模块依赖。

| 文件 | 作用 |
|---|---|
| `viewer/index.html` | 单角色播放器，6 个动画可切 |
| `viewer/compare.html` | 左右对照（原版 vs 换皮后） |
| `viewer/one.html` | 按 URL 参数加载任意 rig，**二分定位用** |
| `viewer/bisect.js` | 批量跑多个 rig，输出 OK/FAIL 表 |
| `viewer/shot.js` | puppeteer 截图 |
| `tools/inspect_mesh.py` | 列 mesh 的类型/顶点数/有无权重 |
| `tools/inspect_stride.py` | 从 `uvs` 反推每顶点 stride |

**截图避坑**：`waitUntil: "networkidle2"` 会永远超时 —— 播放器有 `requestAnimationFrame` 常驻循环。
用 `domcontentloaded` + 固定 `sleep`。

---

## 四、Spine runtime 4.3 的 API 变化（实测）

这几条是从 `spine-player.js` 源码里挖出来的，文档里没有。

| 操作 | 旧写法（无效） | 4.3 正确写法 |
|---|---|---|
| 播放器字段 | `jsonUrl` / `atlasUrl` | **`skeleton` / `atlas`** |
| 取槽位附件 | `slot.getAttachment()` | **`slot.pose.attachment`** |
| 找 atlas | `skeleton.data.atlas` | `null` → 走 `slot.pose.attachment.sequence.regions[0].page` |
| 换整页纹理 | — | `page.setTexture(tex)` |
| 改单区域 UV | — | `region.u/.v/.u2/.v2` 可写 |

**`jsonUrl` 报的错是误导性的**：`A URL must be specified for the skeleton JSON or binary file.` —— 看起来像没传参，其实是字段名不对。

---

## 五、当前真实状态

```
✅ 图集解析        atlas.py 已验证，27 区域往返无损
✅ Rig 加载        rig.py 已验证（20 骨骼 / 27 槽位 / 6 动画）
✅ 比例推断        align.py 已修 atlas scale 补偿
✅ 联动修改        propagate.py 已修变长顶点
✅ 合成导出        replace.py + export.py 已修空槽位/类型
✅ 端到端渲染      通过，左右对比 scale 1.97 → 0.985
✅ 单元测试        78 个全绿（新增 49 个，覆盖 4 条关键回归）
⚠️ 新件位置偏移    约 5px（append padding 未计入），未修
❌ server/         空目录
❌ web/            空目录
❌ 热重载          未开始（运行时 API 已验证可行）
```

---

## 六、下一步（渐进，一次一件）

按这个顺序做，每件都能独立验收：

1. ~~**单元测试** —— 把上面 4 个 bug 钉死~~ ✅ 已完成（见第八节）
2. **修 5px 偏移** —— `append_to_page` 的 padding 要参与 `x`/`y` 计算
3. **`server/`** —— 最小 HTTP：一个 `/reskin` 接口，返回新图集 + 新 UV
4. **`web/`** —— 三栏：左播放器 / 右部件列表 / 下动画栏
5. **热重载** —— 前端 `setTexture` + 改 `region`，不落盘不刷新

**别一次跨两步。** 每步做完先验证，再开下一步。

---

## 七、踩过的坑（按重要度）

| # | 现象 | 根因 | 修法 | 防呆 |
|---|---|---|---|---|
| 1 | `appliedPose` undefined | mesh 顶点按固定 stride 切，骨骼索引被乘坏 | `_parse_vertices` 按 N 解析 | 先跑 `inspect_stride.py` |
| 2 | 头放大 2 倍 | 没补偿图集 `scale: 0.5` | `source_size / page.scale` | 读图集先看 `scale` |
| 3 | `appliedPose` undefined | 给空槽位凭空造附件 | 拒绝空槽位 | 检查 `attachment: null` |
| 4 | 解析异常 | `width` 写成浮点 / 整数混用 | 按原类型 cast | 对照原文件类型 |
| 5 | 加载失败提示误导 | 4.3 改名 `jsonUrl → skeleton` | 用新字段名 | 报错时先搜源码 |
| 6 | 截图永远超时 | `networkidle2` 遇上 rAF 循环 | `domcontentloaded` + sleep | — |

**通用方法**：崩了先**二分**（`bisect.js`），别猜。
本次 4 个 bug 有 3 个是二分定位出来的，猜的全错。

---

## 八、测试覆盖（已固化）

`pytest` 全量 78 个测试，1.4 秒跑完。新增 49 个，集中在换皮线。

### 四个测试文件

| 文件 | 数量 | 覆盖模块 |
|---|---|---|
| `tests/test_atlas_format.py` | 12 | `assets/atlas.py` |
| `tests/test_reskin_align.py` | 11 | `reskin/align.py` |
| `tests/test_reskin_propagate.py` | 17 | `reskin/propagate.py` |
| `tests/test_reskin_replace.py` | 9 | `reskin/replace.py` |

### 四条关键回归（钉死真实崩溃过的 bug）

| 目标 | 测试函数 | 断言什么 |
|---|---|---|
| 图集往返无损 | `test_roundtrip_is_lossless` | 序列化再解析，`Region` 全字段相等 |
| 空槽位拒绝 | `test_empty_slot_is_rejected` | `attachment: null` 抛 `ValueError`（信息含 "currently empty"） |
| 变长顶点 | `test_weighted_vertex_keeps_bone_indices_and_weights` | 骨骼索引 `10`/`9` 不变，权重 `0.5` 不变，只有 x/y 缩 |
| 图集 scale 补偿 | `test_atlas_scale_compensation` | 同组数据：未补偿得 `2.0`，补偿后得 `1.0` |

### 测试写法上固定的几条原则

1. **测 bug 本身，不只是测功能** —— 用真实崩溃过的倍率 `1.970464`，不只用 `0.5`
2. **用对照组证明因果** —— `source_scale=1.0` 拿 2.0，`=0.5` 拿 1.0，证明差异来自补偿
3. **显式测“不应该被改”** —— `width`/`height` 不缩、`rotation` 不缩、无关骨骼不动、空槽位不被污染
4. **真实数据兜底** —— `skipif` 守门的 owl 图集测试，验证 `scale: 0.5` 和 27 个区域

### 自查发现的问题

写 `test_page_grows_when_new_art_does_not_fit` 时用了全透明 sprite，被 `_opaque_box` 正确拒绝。
**这是测试的错，不是代码的错** —— 拒绝空图是正确行为。改测试用有内容的图。
顺带又验证了一条：空图会被拒绝。

---

_最后更新：2026-11-07 · 单元测试完成（78 绿）_
