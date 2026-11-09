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

---

## 九、提示词外置为配置文件（2026-11-07 晚，第 2.5 步先做）

### 为什么要做

第一次真实生图（owl 头 → 鸽子头）暴露的问题：提示词硬编码在 `skins/prompts.py`，
而**「keeping exactly the same art style as the reference」这句话把物种锁死了**——
模型交回来的还是那只猫头鹰脸盘，只是重画了一遍。改措辞要改代码、要重跑测试，
业主明确要求：模板独立成配置文件，以后改风格只改配置。

### 加了什么

| 文件 | 状态 | 说明 |
|---|---|---|
| `config/prompts.json` | 【新增】 | 模板 + 词库 + 负面词，人改这个文件即可调指令 |
| `src/spine_forge/skins/prompts.py` | 【重写】 | 只负责按模板填空；配置缺失/写错会报出文件和键名 |
| `tests/test_skins_prompts.py` | 【新增】 | 20 个测试，钉住这次实测踩到的三个坑 |
| `.env.example` | 【改动】 | 新增 `SPINE_PROMPTS_FILE`（可选覆盖配置路径） |

### 配置文件的位置规则

`config/prompts.json` 是**仓库级配置**，与 `.env`（密钥）并列：
密钥走 `.env`，非密钥的声明式内容走 `config/`。查找顺序：`SPINE_PROMPTS_FILE` →
仓库根 → 从当前目录往上找。改了文件不用改代码，`load_config()` 按路径缓存。

### 三条被实测钉死的规则

1. **只要技法，不要形状**
   旧写法 `keeping exactly the same art style` → 模型整只复制参考图。
   新模板：`Keep only the reference's rendering technique ... discard its shapes and proportions`。
2. **几何必须单独成句**
   只说「画成鸽子头」不够，模型会继承参考图轮廓（耳簇、脸盘、环状眼窝）。
   新增 `part_structure` 词库，按部件给「必须改掉的几何特征」。
3. **冠词不能重复**
   `as a {subject}` + 调用方传 `a pigeon head` → `as a a pigeon head`。
   `normalize_subject()` 负责去重。

### 第三次实测（默认配置，无任何自定义措辞）

指令原文：
```
Redraw the subject in the reference image as a pigeon head. Keep only the reference's
rendering technique - brushwork, shading, palette, edge treatment - and discard its
shapes and proportions: soft painterly 2D rendering, smooth airbrushed shading, visible
brush texture, muted warm palette, crisp clean silhouette, no black outline. Required
geometric changes: the silhouette follows the new species, never the reference: no
inherited ear tufts, facial disc, ringed eye sockets or neck ruff. Viewpoint: strictly
front view, symmetrical... Composition: the head and face plate only, blank surface,
no eyes, no pupils, no beak... Background: one plain solid colour...
```

结果：**物种换对了**（圆颅顶、灰羽、无耳簇无脸盘），笔触/配色贴近参考。
**但五官仍然泄漏**——模型自带眼睛和喙，违反了「脸盘留白」的规则，负面词压不住。
尺寸照旧不受控（要 597×474，返 2288×1824），`postprocess.prepare()` 抠底归一后
不透明区 369×468（参考 591×467）：高度对上了，宽度窄了 38%，因为参考脸盘是宽扇形。

### 还没解决（下一步候选）

1. **五官泄漏**：靠后处理遮罩（`assets/matting.py`）比跟模型较劲可靠
2. **宽度比例**：`normalize_to_reference` 只按高度归一，宽高比差得多时会被压扁

---

_最后更新：2026-11-07 · 提示词外置（120 绿）_

---

## 十、脸盘五官遮罩（第 1 步：几何模块，已测；接入 reskin 待做）

### 为什么要做

提示词压不住五官：负面词里明写了 `eyes, eyeballs, pupils, iris, eyelashes, beak, nostrils`，
qwen-image 照样给鸽子头画了眼睛和喙。而 rig 里眼睛、喙是**独立附件、独立骨骼**，
生成件再画一遍就是双画。跟模型较劲不如用几何遮罩。

### 加了什么

| 文件 | 状态 | 说明 |
|---|---|---|
| `src/spine_forge/skins/faceplate.py` | 【新增】 | 从 rig 算五官位置 → 椭圆遮罩 → 用周边中位色填平（`fill`）或挖透明（`clear`） |
| `tests/test_skins_faceplate.py` | 【新增】 | 20 个测试，含 owl 真实 rig 回归 |

`skins → core` 方向，依赖合规；不与 `matting.py`（抠背景）、`postprocess.py`（归一）混职责。

### 关键实现细节（都是踩出来的）

- **mesh 顶点是变长流**：`[boneCount] [boneIndex x y weight] * boneCount`，
  `boneCount == 0` 时是 `[x y]`。按 `0::2` 硬切会得到 300px 宽的眼圈（597px 的脸盘上），
  第一版就是这么错的，已由 `_decode_vertices` + 回归测试钉死。
- **加权顶点跨骨**：每个顶点按权重混合多根骨骼的变换，所以要先算 `bone_matrix(骨 → 脸盘骨)` 再求和。
- **y 轴翻转**：Spine 骨骼 y 向上，像素 y 向下，`top = cy + h/2` 处翻。
- 填色取**环形区域中位色**（1.08/1.25/1.45 三圈，忽略透明像素），比均值抗单点离群。

### 真实图验证（illustration 风格生成件）

遮罩确实生效（8 个 zone 全部填充，`skipped: []`），**但位置对不上**：
owl 的 iris 网格换算到脸盘上半径约 110px，而生成件自己把眼睛画在了更靠上的位置，
于是出现两个米色大圆盘，生成的眼睛反而露在外面。

**结论**：遮罩的坐标是 rig 坐标系，必须在**贴进 rig 之后**做（`apply_reskin` 里对齐完成时），
而不是在独立预览图上按包围盒比例硬映射。这一步留给第 1b 步。

---

_最后更新：2026-11-07 · 五官遮罩几何模块（140 绿）_

---

## 十一、五官遮罩接进 apply_reskin（第 1b 步，已接；位置匹配仍未解）

### 加了什么

| 文件 | 状态 | 说明 |
|---|---|---|
| `src/spine_forge/reskin/replace.py` | 【改动】 | 新增 `blank_features` / `feature_padding` / `feature_feather` 三个参数；掩膜在**裁出 sprite 之后、拼页之前**执行；`ReskinResult.features` + `report()["features"]` 汇报 |
| `src/spine_forge/skins/faceplate.py` | 【改动】 | 抽出 `plate_geometry()`（返回 `left, top, w, h`），`feature_zones()` 改为复用，行为不变 |
| `tests/test_reskin_feature_mask.py` | 【新增】 | 8 个测试 |

**为什么在这个位置做**：遮罩必须与像素在同一坐标系。`trimmed` 就是即将贴进图集的 sprite，
此时把 plate 坐标按 `trimmed/plate` 的盒子比例映射过去，再原地填色——比在独立预览图上猜比例可靠。

**默认值**：`blank_features=False`。默认关是因为它会改像素，调参/对比时不该被静默影响；
真正换皮时由调用方显式打开。推荐 `feature_padding=4~8`、`feature_feather=6~8`。

### 测试

```
148 passed（新增 8）
```

覆盖：默认不动像素 / 打开后五官区被抹掉而其余像素逐字节不变 /
遮罩随 sprite 等比放大（2× 脸盘不会留着 1× 的圈）/ padding 真的扩边 / 越界 zone 跳过 /
图集其它像素不被触碰 / 真实 owl rig 的 8 个 zone 全部落在 plate 内。

### 真实素材 E2E（v4 插画头 + 紧裁参考图重生成）

链路跑通：生成 → `prepare()` → `apply_reskin(blank_features=True)` → `write_project()` →
官方 runtime 渲染无页面错误（27 槽位，idle 动画正常）。产物在
`examples/owl/skins/mask-preview2/`（gitignored）。

**但视觉上仍是双画**：模型的五官位置在**上方**（眼睛约 30% 高度），rig 的 eyes/beak 在**中下部**
（约 53%~60%），几何遮罩按 rig 走，于是抹在了脸颊上，模型自己画的小眼睛留在原处。

### 根因（比上一轮更清楚了）

遮罩位置**完全依赖生成件复制参考图的布局**。而当前提示词恰好禁止了这件事：
`Required geometric changes: ... no inherited ringed eye sockets` —— 模型理解为
“五官要重新设计”，于是把眼睛整体上移、缩小。

**紧裁参考图没能救它**：这一版紧裁后重生成，眼睛仍在 30% 高度。上一轮“紧裁后模型照抄布局”的
结论只在那次的具体提示词下成立，不能当通则。

### 下一步（两条，二选一或都做）

1. **改提示词**：把“禁止继承眼环形状”改成“**保留每个五官在画布中的位置与尺度**，
   但那里必须是空的眼窝（blank socket），不画眼珠”；遮罩位置立即可靠。
2. **几何自对齐**：在生成件内找两个最暗的圆形团块（纯阈值+连通域，不用 ML），对齐后
   再套 rig zone。能兜住模型不听话的情况，但要在 `faceplate.py` 里加一层检测。

---

_最后更新：2026-11-08 · 遮罩接入 reskin（148 绿）_

---

## 十二、色块拆分器（新路线第一步：一张平涂图 → 命名部件）

### 为什么要新开一条线

B 线（换皮）的前提是"已经有一套能用的骨架"。用户的新思路反过来：**给一张平涂插画，
先拆成部件，再按部件生成可渲染的 Spine 数据**（骨架点位、附件、图集）。
`D:\Downloads\mix-and-match-4.3` 被当作数据结构参照，见第十三节。

### 加了什么

| 文件 | 状态 | 说明 |
|---|---|---|
| `src/spine_forge/splitter/colors.py` | 【新增】 | 色族分类 → 连通域 → 命名 → 落盘 |
| `tests/test_splitter_colours.py` | 【新增】 | 6 个测试 |
| `examples/girl/parts/*.png` | 产物 | 13 个部件，**保持原始画布尺寸**（不裁切） |
| `examples/girl/preview/` | 产物 | `parts_sheet.png`（部件表）、`reassembly.png`（重组对照） |

### 思路（每一步都是被真实错误逼出来的）

1. **找"填色"而不是找"像素色"**：在 16 级 RGB 直方图上取峰值，峰值之间用 Lab
   色度合并（明度允许 ±22 漂移，笔触阴影不该把一件衣服拆成三块）。
   *先试过 k-means*：它把大片纯色切碎、又把小色块并进邻色 —— 测试图里绿头发和浅绿短裤
   被并成一块，青鞋整块消失。
2. **命名靠色族窗口**（hue + sat + val 上下界），顺序敏感：`orange` 必须排在
   `shirt` 前（同样的色相，裸露手臂更饱和更亮）。
3. **连通域**：行游程 + 并查集，8 连通；`MERGE_GAP=12` 把被凉鞋带切开的袜子重新并回一件。
4. **灰线归属用"邻域多数"**：不能用"谁先扩谁拿走" —— 会被顺序偏置，衬衫会把两条手臂
   的暗描边一起吞进来（真实发生过，导出图里衬衫带着半透明鬼影轮廓）。
5. **孤儿吸收**：小岛若被大件包住（≥75% 边界）且色度接近，算它的阴影；细长笔画另行丢弃。
6. **小色块兜底**：低于直方图阈值的孤岛（眼睛、嘴唇）用自身均色再判一次色族，
   否则眼睛会被周边肤色吞掉（第一版就是"有眼窝没眼睛"）。

### 结果（image_161844278571506.png，896×1184）

13 个部件：`shirt 378×473 / hair 310×264 / head 179×199 / shorts 205×116 /
leg-right 76×261 / leg-left 97×151 / arm-front 195×101 / arm-back 89×194 /
shoe-right 126×79 / shoe-left 76×93 / sock-right 74×92 / sock-left 55×93 / accent 96×81`

覆盖率 96%（前景）；重组后画面均差 14.5/765，肉眼看几乎一致。

### 已知问题

- **描边归属**：细黑线会跟着邻域多数走，个别轮廓（肩线、胯线）在重组图上有断口；
  衬衫件里残留极淡的鬼影描边（右侧/底部）。
- **眼睛是独立件**：`accent` 包含眼球与嘴唇，脸盘上因此留了两个洞 —— 对骨架是好事
  （眼睛本该独立），但如果要"完整脸"就需要合并策略。
- 命名是位置启发式（head/arm/leg 按 cy 分带），不是解剖理解；换姿势的图会失效。

---

_最后更新：2026-11-08 · 色块拆分器（154 绿）_

### 十二·补充（同日，按用户反馈改）

1. **命名改为「角色自身的左右」**：画面朝向观众，所以**观众左手边 = 角色右手**。
   `_side()` 用**角色重心线**（按面积加权的 cx）判断，不用画布中线 —— 这个女孩偏向画面左侧、一只手向右伸，
   用画布中线会让两条腿都判成同一侧。腿/手臂/鞋/袜/眼睛全部按此规则；手臂不再叫 front/back。
2. **多余轮廓线（衬衫、腿）**：三个真正的成因，逐个修：
   - 手臂边缘的抗锯齿像素混出**棕色**，被判进衬衫的调色板 → 在分类后加一次 **邻域多数投票**（半径 1，≥3 票），把边界像素还给真正相邻的填色；
   - 脱离主体的**孤岛**（手指轮廓残片）→ 只保留"与主体相距 ≤3px 或面积 ≥5%"的岛，其余丢弃；
   - **贴在其他部件上的本色描边**（衬衫带着手臂暗线）→ `bleed = 本体 & ~核心周边 & 其他部件周边` 剔除。
3. **教训**：靠加粗形态学开运算去"削细线"会削掉真正的衣摆（实测 2 轮就把衬衫下摆吃掉 80px）。
   颜色归属问题要在颜色层解决，别指望几何补刀。

_修正后：154 passed；衬衫/左腿的多余线圈已去除，残留一条极淡的手部轮廓线（见 parts_sheet 第一格），
愿意的话可以再单独擦除或我加一条"描边层"规则。_

### 十二·2（同日晚，第三轮反馈）

- **袜+鞋合并**：`sock-<side>` + `shoe-<side>` → 单个 `foot-<side>`（视觉上一体、动作同步，不该占两根骨）。测试已改为断言"两条腿各一个 foot，且不再有独立 sock/shoe"。
- **描边层 `outline.png`**：被从部件上剔除的描边像素不再丢弃，统一落到一层（实现方式：`ink` 累积 + 残差；灰度且远离图形的孤岛=水印，丢弃）。
- **衬衫手臂轮廓**：实测那条线**和衬衫同色**（RGB≈203,162,124），不是深色描边，所以颜色无法区分；只能几何剔除。
  现在的判据：`开运算(半径3) 定身体 → 距身体 >3px 的部分` 里，**贴着别的部件** 或 **比本体暗 15 个 L** 的算描边。
  代价：约 20px 的衣摆边缘会被判成描边（已接受，藏在外套/短裤后面）；头发尾梢有轻微损失。
- **仍不完美**：`outline.png` 目前只装"被剔除的碎条"（指尖、缝口、那条手臂线），**不是完整的线稿层**；`hair` 里还残留一小段脱离的发丝。

_最后更新：2026-11-08 · 色块拆分器 v2（154 绿）_

### 十二·3（用户选 A′）

- **取消全局描边层**：剔下来的描边像素直接丢弃，不再生成 `outline.png`。
  理由写进代码注释：全局"剩余物"层不是线稿；真实引擎里描边烤在每个部件的贴图里，部件动线才跟着动。
- 最终部件 **11 个**：`shirt / hair / head / shorts / leg-left / leg-right / arm-left / arm-right / foot-left / foot-right / accent`。
- 已知残留：`hair` 右侧有一小段脱离的发丝（约 100px）；衬衫/短裤/头部因描边剔除各损失 10~25px 边缘。

_最后更新：2026-11-08 · 拆分器交付 v3（154 绿）_

---

## 十三、拆分流程固化（文档 + 流水线挂接）

用户要求「把相关流程和所有坑点写成 md，把流程固化下来」。做了三件事：

### 1. 文档：`docs/parts-splitting.md`

操作手册 + 坑点档案，共 13 条工程/算法坑（k-means 不可用、同色相族要带饱和度/亮度界、
绿发 vs 浅绿短裤只能靠明度、形态学削细线会削真衣服、那条"手臂轮廓"与衬衫同色、
灰线归属不能"先扩先得"、抗锯齿混色、小色块低于直方图阈值、孤岛剪枝、左右命名要用角色重心线、
全局描边层是垃圾场、alpha 写法、部件必须互斥且全画布对齐）。另附参数表、验收口径、已知限制。

### 2. 流水线挂接（不再依赖 `_tmp` 脚本）

| 文件 | 状态 | 说明 |
|---|---|---|
| `src/spine_forge/splitter/colors.py` | 【改动】新增 `ColourSplitter` | 实现 `Splitter` 协议，可直接被 `stages.split` 使用 |
| `src/spine_forge/splitter/report.py` | 【新增】 | 拼版图 + 重组校验（覆盖率/均差），与拆分逻辑解耦 |
| `src/spine_forge/stages/split.py` | 【改动】 | 加 `kind="alpha"|"colour"`、`previews=`；默认产出 `preview/`；把 coverage/mean_diff 写进 parts.json 与返回值 |
| `src/spine_forge/cli.py` | 【改动】 | `split --splitter {alpha,colour}`、`--no-preview` |
| `README.md` | 【改动】 | 命令表补 splitter 选项 + 文档入口 |
| `tests/test_splitter_colours.py` | 【改动】 | 新增 2 个流水线用例（stage 产出四件套、未知 splitter 报错） |

### 3. 一条命令复现

```bash
python -m spine_forge.cli split <图片> --out <目录> --splitter colour
# parts: 11 / coverage: 0.935 / mean_diff: 25.24
```

_最后更新：2026-11-08 · 拆分流程固化（156 绿）_

---

## 十四、按用户手标关节重建骨架（girl）

用户在原图上画了黑色椭圆圈标关节（`D:\Downloads\image_161844278571506_骨架标记.png`），要求以标记为准、缺的按 mix-and-match 补。

### 怎么把标记读出来

标记是**空心圆环**，所以用"洞"来找而不是暗色团块：
背景从边界 flood fill → 没被填到的亮区就是环内洞 → 洞的质心 = 关节。
`find_rings.py` 实测 20 个洞（有一处环被发丝切成两个洞，合并），另有一个环洞太窄
（`(354,646)`）检测不到，按 5 倍放大目视补上。眼睛/眉毛是实心暗块，不会误判。

### 骨架（20 根）

`root → hips → chest → neck → head → hair`；两臂 `shoulder_* (零长控制骨) → arm → fore → hand`；
两腿 `leg → shin → foot`。关节坐标全部取自用户标记（见 `examples/girl/rig/user_marks.json`），
用户没标的 `root / hips / neck / head-tip / foot-tip` 按示例结构补。

### 教训

- 手标位置优先于任何自动推算；自动检测只用于**把标记转成数字**，不用于判断关节该在哪。
- 环检测比暗色团块检测稳：实心暗区（瞳孔、眉毛）与暗线条（发丝）都不会产生"洞"。

产物：`examples/girl/rig/{skeleton_panel.png, bones.json, user_marks.json}`。

_最后更新：2026-11-08 · 骨架按手标重建_

---

## 十五、骨架生成独立成模块（rig/ + skeleton 子命令）

用户要求：把"手标关节 → 骨架 + 交付图"的方法记录下来，并把骨架生成做成单独模块。

### 结构

| 文件 | 职责 |
|---|---|
| `src/spine_forge/rig/markers.py` | 读空心圈：暗色掩膜 → 边界 floodfill → 未被填到的亮区=洞 → 质心=关节；`merge_close_marks` 合并被切开的环；`nearest_mark` 供吸附 |
| `src/spine_forge/rig/skeleton.py` | `Joint` / `Skeleton`；`spine_bones(H)` 做 y 翻转 + 局部变换；`load_spec` / `save_spec` |
| `src/spine_forge/rig/overlay.py` | 审阅图：原图 1:1 + 骨头按链上色 + 右侧坐标表 |
| `src/spine_forge/stages/skeleton.py` | stage：读标记 → 吸附 → 写 `marks.json` / `marks_numbered.png` / `joints.json` / `bones.json` / `skeleton_panel.png` |
| `src/spine_forge/cli.py` | 新增 `skeleton` 子命令：`--marks` / `--joints` / `--no-snap` |
| `docs/skeleton-from-marks.md` | 流程 + 标记画法 + 算法 + 换算规则 + 验收 + 限制 |
| `tests/test_rig.py` | 13 个用例 |

### 关键设计决定

- **位置以人的标记为准**：自动检测只把标记转数字，不判断关节该在哪；骨段走向仍写在 `joints.json`（base/tip），因为那是艺术判断。
- **吸附要留痕**：表里的点离最近的标记 ≤12px 会被拉过去，并在 `bones.json.snapped` 里记录"哪个点、移了多少、落到哪"。不一致永远看得见。
- **y 只翻一次**：图像 y 向下、Spine y 向上，换算只发生在 `spine_bones()`，下游不再翻。
- **子骨偏移必须算**：腿从骨盆侧面长出，不能假设"子骨 x = 父骨长度"。
- **审阅图 1:1 贴原图**：缩放会让"看起来在手臂上"变成假象。

### 复现（girl）

```bash
python -m spine_forge.cli skeleton art.png --out examples/girl/rig \
  --marks art_marks.png --joints examples/girl/rig/joints.json --name girl
# marks: 20 / bones: 20 / snapped: 2 (1.5px, 1.8px)
```

**169 passed**（原 156 + 新增 13）。

_最后更新：2026-11-08 · 骨架模块化（169 绿）_


### 十五·补充：IK 与跟随约束（按示例字段生成）

- 新增 `src/spine_forge/rig/constraints.py`：`IkSpec` / `FollowSpec` / `add_ik_targets` / `default_constraints` / `validate`。
  字段形状照抄示例：`{"type":"ik","target":...,"bones":[父,子],"bendPositive":false}`、
  `{"type":"transform","source":...,"bones":[...],"properties":{...},"mixRotate":...}`。
- girl 的 `joints.json` 增加 5 根零长控制骨（`head-control`、`ik_foot_r/l`、`ik_hand_r/l`）与 6 条约束：
  4 条 IK（脚 ×2、手 ×2）+ 2 条 transform（head-follow 1.0、hair-follow 0.35）。
- **不做 path 约束**：需要 path 附件，这套拆分没有对应美术；以后加是"新附件 + 一条约束"。
- stage 现在会：读 spec 的 constraints（没有则用 `default_constraints`）→ `validate()` 校验
  （目标/源/骨名是否存在、IK 链至少两骨）→ 写进 `bones.json`。校验不过直接报错，不留到 Spine 里炸。
- 修了一个真 bug：吸附阶段会把零长度目标骨的 tip 拉到另一个标记上，造出 1px 长度 → 现在零长度骨的 tip 强制等于 base。
- 审阅图：控制/目标骨画成**橙色菱形** + 虚线连到被驱动的关节。
- 测试：`tests/test_rig_marks.py` +5（共 18），全库 **174 passed**。

_最后更新：2026-11-08 · IK 与跟随约束（174 绿）_

---

## 十六、部件挂到骨上 → 可运行的 Spine 工程（assemble）

用户："肘/膝切分暂不处理，接下来是把部件挂上去"。

### 新 stage：`stages/assemble.py`

`parts.json + bones.json → skeleton.json + atlas + page`，产物在 `examples/girl/dist/`：

```
girl.json     25 骨 / 11 槽 / 6 约束 / default skin 11 个 region 附件
girl.atlas    scale 1，11 个 region
girl.png      896×1024 图集页
runtime.png   官方 runtime 渲染截图
```

### 三处必须做对的换算

1. **空间**：部件在图像像素（y 向下），Spine 是 y 向上 —— 只在求世界坐标时翻一次。
2. **骨骼坐标系**：骨是旋转的，附件偏移写在该骨坐标系里会被带着转。所以
   `attachment.rotation = -骨世界角`，偏移用 `R(-骨世界角)` 反旋；最终世界角 = 0（正立）。
3. **打包**：atlas 的 bounds 是页面像素；本步按 scale 1 打包，避免半像素误差。
   图集页必须和 `.atlas` **同目录**（atlas 首行是相对 atlas 的路径），否则运行时 404。

### 绘制顺序（slot 顺序即 z 序）

`leg-r → leg-l → foot-r → foot-l → shorts → hair → shirt → arm-right → head → accent → arm-left`

### 验证

写了一个独立的校验脚本（`_tmp/check_attach.py`），按运行时的变换链重算每个附件的世界位置，
与源图部件中心对比：**11/11 偏差 0.0px，旋转全部 0.0°**。

### 运行时踩坑（都修了）

- `animation: "idle"` 报 "Animation does not exist" —— 首版没有动画，预览要留空。
- `bendPositive` 固定 false → 左手臂翻到头上；改为按姿势叉积计算（腿 false / 臂 true）。
- transform 约束带 `properties` 范围块 → 头被拧 60°；去掉范围块，只用 mix。

**176 passed**（原 174 + 新增 2 个约束弯向用例）。

_最后更新：2026-11-08 · 部件挂接（176 绿）_

### 十六·补：`assemble --mode images`（Spine 编辑器读不了图集时的方案）

用户的 Spine 打不开我们的图集（只能读分开的部件图）。新增 `--mode images`：

- 产物：`<out>/girl.json` + `<out>/images/*.png`（11 张，按附件名命名），**不生成 atlas**；
- `skeleton.images = "./images/"`，Spine 按附件名到该目录找图；
- 附件数值（x/y/rotation/width/height）与 atlas 模式完全一致 —— 两种模式只是取图方式不同。

```bash
python -m spine_forge.cli assemble parts.json --bones rig/bones.json \
    --out examples/girl/spine-images --name girl --mode images
```

产物位置：`examples/girl/spine-images/`（图集版仍在 `examples/girl/dist/`）。

_最后更新：2026-11-08 · images 模式（176 绿）_

### 十六·补二：膝关节切分（用户拖动 IK 时腿不弯）

**现象**：拖 `ik_foot_r` 时凉鞋飞走、腿纹丝不动。
**根因**：腿是**一整块**贴图，绑在 `leg_*`（大腿骨）上；IK 转动的是 `shin_*`，而 `shin_*` 身上
没有任何贴图 —— 骨在动，画没动。这不是 IK 配置错，是"一块刚性贴图不可能形变"。

**处理**（用户此前说"肘/膝暂不处理"，但这里必须先切，否则膝根本弯不了）：

1. **腿在膝盖处切开**：沿过膝关节点、垂直于大腿方向的直线切，得到 `leg-*-up` / `leg-*-down`，
   分别绑到 `leg_*` / `shin_*`。两半保留全画布坐标，原有摆位公式不变。
2. **手臂改绑前臂**：可见的手臂贴图本来就是"前臂+手"（上臂被袖子遮住），
   所以从 `arm_*` 改绑到 `fore_*`，肘部旋转立刻可见。
3. `assemble --mode images` 现在会先清空 `images/` 再写，避免残留旧部件图（之前 15 张里 2 张是旧的）。

**验证**：把 `shin_r +42°`、`shin_l -34°`、`fore_l +18°` 摆一版，官方 runtime 渲染
（`examples/girl/dist/pose_bend.png`）：膝盖正常弯、脚跟着走、贴图不撕裂。

槽位从 11 → 13。**176 passed**。

_最后更新：2026-11-08 · 膝关节切分_

## 十七、腿部改成「整图蒙皮」（用户：官方示例是扭曲变形，不是分割）

用户："不是我观察官方的实例中，腿部图片是可以做扭曲变形的，不是做的分割"。

上一节（十六·补二）的做法是**把腿切两半**、各绑一根骨 —— 那是"两根刚体各转各的"，
把 IK 目标拉远一点，膝盖处就是两个分开的 **V 形缺口**，而且切线上永远有一条接缝。
复查：之前记的"贴图不撕裂"只在 ±40° 内hold住，位移到 40/50px 就露馅（见对比图左）。

### 做法：加权网格（skinned mesh）

`assemble --warp legs` → `rig/mesh.py`：

1. 把 `leg-*-up` / `leg-*-down` 按 **alpha 取较不透明者** 拼回整条腿
   （两半来自同一张图，颜色相同、只有 alpha 不同；用 `alpha_composite` 会在 1px 羽化带上 >1.0 留下接缝）。
2. 在整条腿的 bbox 上铺规则网格（≈12px 一格，腿左 6×18、腿右 9×14）。
3. 每个顶点按"到膝关节的投影距离"加权到 `leg_*` / `shin_*`：关节两侧各 10px 做 smoothstep 过渡，
   其余顶点 100% 单骨。
4. 输出 Spine `type: "mesh"` 附件；槽位 13 → 11（每腿一个槽）。

### 两个静默坑（都不报错，只是图错）

| 坑 | 现象 | 正确做法 |
|---|---|---|
| 权重顶点格式 | 顶点全挤在一起 / 人形消失 | 每顶点 `boneCount` + `boneCount × (骨索引, x, y, 权重)`；x/y 是同一世界点在**各自骨局部系**的坐标 |
| mesh 的 `uvs` | 腿变成一整块纯色矩形 | uvs 是**图内 0..1**（运行时用 region bounds 再换算），不是图集绝对坐标；且 `v=0` 在**上沿** |

（第一版把 uvs 写成图集绝对坐标 → 渲染出两块红矩形；第二版把 v 写成"下沿 0" → 上下镜像。
都是靠 runtime 截图对比才发现的。）

### 验证

```
python -m spine_forge.cli assemble examples/girl/parts.json --bones examples/girl/rig/bones.json \
    --out examples/girl/dist-warp --name girl --mode atlas --warp legs
python -m spine_forge.cli assemble examples/girl/parts.json --bones examples/girl/rig/bones.json \
    --out examples/girl/spine-images-warp --name girl --mode images --warp legs
```

- 静止姿势 vs 分割版：**平均像素差 0.031**（1080k 像素里 604 个 >8，全在腿边缘抗锯齿），即完全重合。
- 弯曲姿势（拖 IK：`ik_foot_r +(22,42)`、`ik_foot_l +(-14,30)`）：
  `examples/girl/compare-knee-warp.png`（左=分割版撕裂 / 右=网格版平滑弯曲），
  官方 runtime 渲染无页面错误。
- 关键回归测试：`tests/test_rig_mesh.py` —— 顶点权重和为 1、**静止姿势能逐点反算回原图像素**（1e-3）、
  只转 `shin` 时"大腿半边不动、小腿半边动、膝盖行介于两者之间"、uvs/hull/edges/triangles 结构自洽。

**190 passed**（原 176 + 新增 14）。

### 仍不完美

- 线性混合蒙皮（LBS）在膝内侧会轻微"收窄/发软"，没有真实膝盖的折痕；要折痕得加第三条辅助骨或调窄过渡带。
- 目前只有腿走 warp；手臂（前臂+手）仍是整块绑 `fore_*`，同理可加。

_最后更新：2026-11-09 · 整图蒙皮（190 绿）_

### 十七·补：权重泄漏（用户："你这个做的拖动膝盖会脱节"）

**现象**：用户在编辑器里拖膝盖 / 抬脚，腿的大腿段被拽走，出现一块**苍白的大弯月**，
看起来像膝盖脱节（IK 本身没坏：静止姿势与分割版逐像素重合，说明 bendPositive 是对的）。

**根因**（不是 IK，是权重）：第一版按「顶点到**小腿轴线**的投影距离」分权重。
贴图框的左上角离膝盖 **80px**，但沿小腿方向的投影只有 **-7.7px**，正好落在 ±10px 过渡带里
→ 这块大腿被分给了 `shin_*`，"大腿骨"只覆盖一半。拖膝盖时那一半就被小腿拖走。

**改法**：`rig/mesh.py` 新增 `_chain_param()`，沿 **髂→膝→踝整条骨链**找最近点、算弧长参数 s，
再用 `s` 与膝点的弧长差做 smoothstep。框角离腿远也没关系，它归到最近的**那一段**（大腿段）。

**验证**（官方 runtime，三种拖法）：
- A 直接拖 `shin_r`（膝盖）、B 拖 `ik_foot_r` 上抬、C 拖到超出可达范围
- 三张图里大腿都是实色、无苍白弯月、无撕裂、鞋跟着走（`_tmp/probe_compare_fixed.png`）
- 静止姿势 vs 分割版：平均像素差 **0.031**（未变，说明只修了形变、没动摆位）

**回归测试**（`tests/test_assemble_warp.py`，3 条）：用仓库里的真实 girl 数据跑 `assemble --warp legs`，
断言「腿的**顶行顶点**必须只绑大腿骨」——旧算法下这一条会失败（顶行左角被 blend 到小腿），
即测试能复现原 bug；另外两条守"每腿一个 mesh / 槽位 11"和"膝盖过渡带还在"。

**193 passed**（190 + 3）。

### 关于"官方是路径曲线"的结论（暂不改）

对照实例截图（`leg-back-path` / `arm-back-path`）确认那是 **Path 约束**，但：

1. path 只**搬运骨骼**，贴图形变仍靠 mesh 权重 —— 我们已经有 mesh，缺的只是"拖曲线"这个手柄；
2. 官方能弯成**平滑弧线**是因为腿是一串 3~5 节骨被曲线均匀吸住，我们只有 thigh+shin 两节，
   只能折不能弧；
3. path 约束会**接管这串骨的 rotation**，与现有 `ik_foot_*` 抢同一批骨，二者不能同时生效。

所以要做成官方那样，需要先加"腿骨链细分 + 变形骨"，再挂 path；用户当前的手感（拖脚踝抬腿）
本来就是 IK，先把手感的 bug 修完为止。

_最后更新：2026-11-09 · 权重泄漏修复（193 绿）_
