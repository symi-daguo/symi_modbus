# symi_modbus 修复操作记录（2026-11-06）

> 本文件从 `操作记录.md` 中单独拆出，只记录 **symi_modbus 集成 4 项代码修复** 这一件事，可独立归档/交付。
> 排查「0B 控制不了」、输出待修改清单、FLK 品牌接入等内容仍留在 `操作记录.md`，本文只引用结论。

| 项 | 内容 |
|---|---|
| 日期 | 2026-11-06 14:26 ~ 14:46（北京时间） |
| 目标主机 | `192.168.2.61` / casaos25（SSH `symi`，HA 跑在 Docker 容器 `homeassistant`） |
| 配置根目录 | `/DATA/AppData/homeassistant/config`（容器内挂载为 `/config`） |
| 对象 | 自定义集成 `custom_components/symi_modbus` |
| 结果 | 4 项修复全部部署、重启、验收通过；设备状态与修改前一致 |
| 用户决定 | 清单 **2（联动标题）、3（设备同名）、5（coil_count）不改** —— 测试用，实际落地自行改名称/应用 |

---

## 一、修复项来源

上一轮排查确认「0B 控制不了」是联动目标指向 0A（用户有意配置），并非故障。随后全量复核输出 8 条待修改清单，用户指定只修代码层的 4 项：

| 编号 | 问题 | 处理方式 |
|---|---|---|
| **1** | 改配置触发重载时，实体刚建、`_attr_available=False`，`LinkageGroup.async_start()` 立即同步，`_async_apply` 对 unavailable 实体发服务被 HA 丢弃 ⇒ 每次改配置丢一次「继电器状态→面板灯」同步 | **已修** |
| **4** | `linkage.py:112` `always=True` + 状态回环，一次按键向面板重复发 **3 次** `01 06 00 32 ...` 写灯帧 | **已修** |
| **6** | `configuration.yaml` 无 logger 段，默认 WARNING 把集成 INFO/DEBUG 全吞了，排障只能靠 diagnostics | **已修** |
| **7** | `connection.py:33` `RECENT_FRAMES=40`，轮询约 4 帧/秒只覆盖 10 秒，抓帧窗口太短 | **已修** |
| 2 / 3 / 5 | 联动标题只显示首个 relay / 0A 与 0B 设备同名 / 32 路线圈产生 64 个实体 | **按用户要求不动** |
| 8 | 验证期间 0A 前 12 路、0B 前 16 路变 on 但帧缓冲无对应写帧，疑似总线上有第二写入源 | **未复查，仍未确认** |

---

## 二、改动文件（3 个，`__init__.py` 未改）

根目录 `/DATA/AppData/homeassistant/config/`：

| 文件 | 改动 | 对应 |
|---|---|---|
| `custom_components/symi_modbus/linkage.py` | 整份重写启动/写入逻辑 | 1、4 + 回归防护 |
| `custom_components/symi_modbus/connection.py` | `RECENT_FRAMES` 40 → 200 | 7 |
| `configuration.yaml` | 末尾追加 `logger.logs` 三段 | 6 |

**`__init__.py` 刻意不改**：启动时序修复全部收敛在 `LinkageGroup` 内部，`async_setup_entry` 仍是 `await group.async_start()`，把改动面压到最小，便于回滚和移植。

### linkage.py 实现要点

1. **重载同步不再丢（#1）**：`async_start()` 不再立即同步，改为 `_schedule_initial_sync()` —— 只要还有实体是 `unavailable/unknown`，就注册一次性状态监听 + `INITIAL_SYNC_TIMEOUT=5.0s` 兜底定时器；等 relay 实体真正就绪（hub 首轮询回包）才 `_finish_initial_sync()` 执行「继电器状态 → 面板灯」同步。`_async_apply()` 遇到目标 unavailable 不再直接发服务，改为 `APPLY_RETRY_DELAYS=(0.5, 1.0, 2.0)` 有限重试；后台任务进 `_tasks`，`async_stop()` 统一 cancel + gather。
2. **灯帧去重（#4）**：只对**面板实体**按 `(entity_id, state)` 做 `LED_DEDUPE_WINDOW=0.3s` 去重；**继电器帧不去重**（场景模式可能重复同一线圈命令、跨从站双 relay 必须各发一帧）。
3. **启动静默（回归防护，关键）**：`_async_state_changed()` 在 `_sync_done=False` 或 `time.monotonic() < _settle_until`（`STARTUP_SETTLE_WINDOW=2.0s`）时直接 return。原因见第四节。
4. **日志（#6）**：`custom_components.symi_modbus: info`，并对 `...connection`、`...linkage` 单独设 **debug** —— 帧日志 `Sent/Read N byte(s)` 是 debug 级，只设 info 看不到帧。

### configuration.yaml 追加的片段

```yaml
logger:
  logs:
    custom_components.symi_modbus: info
    custom_components.symi_modbus.connection: debug
    custom_components.symi_modbus.linkage: debug
```

> ⚠️ 这是**增量片段**，不是整份配置。该文件含 `!include` / `!include_dir_merge_named` 等 HA 自定义 YAML 标签，绝对不能用 PyYAML 之流读进来再 dump 回去，只能纯文本追加或手工合并。

---

## 三、备份与回滚

修改前原版已备份（同目录，**未被覆盖**）：

| 备份 | 大小 |
|---|---|
| `configuration.yaml.bak-fix-20261106` | 265 B |
| `custom_components/symi_modbus/linkage.py.bak-fix-20261106` | 5920 B |
| `custom_components/symi_modbus/connection.py.bak-fix-20261106` | 10059 B |

回滚一条命令：

```sh
D=/DATA/AppData/homeassistant/config
sudo cp "$D/configuration.yaml.bak-fix-20261106" "$D/configuration.yaml"
sudo cp "$D/custom_components/symi_modbus/linkage.py.bak-fix-20261106" \
        "$D/custom_components/symi_modbus/linkage.py"
sudo cp "$D/custom_components/symi_modbus/connection.py.bak-fix-20261106" \
        "$D/custom_components/symi_modbus/connection.py"
docker restart homeassistant
```

（FLK 品牌那轮的 `.bak-flk-20261106` 备份也在，两套互不覆盖。）

---

## 四、回归事件（务必留档）

第一次部署后触发 `homeassistant.reload_config_entry` 验收，**0A 前 4 路 / 0B 前 2 路被真的关掉了**：日志出现 10 条 `0a/0b 05 ... 00 00` 关帧，线圈 bitmask `FF 0F` → `F0 0F`、`FF FF` → `FC FF`。

**根因**：旧代码服务调用被 HA 拒绝，反而没写成；加了「unavailable 重试」后服务能成功，而重载时实体会以**恢复/默认状态 `off`** 上报一次状态变化，联动把它当成真实按键，反向把继电器写成 off。

**修复**：加 2s 启动静默 + 初始同步完成前静默，初始同步改由独立就绪监听触发且**只写面板灯、不动继电器**。补了专门单测「启动期 4 次恢复状态事件 → 0 次服务调用」。重新部署后重启，启动期写线圈帧 **0 条**。

被误关的 0A 01-04、0B 01-02 已于 14:45 全部恢复为 on，最终设备状态与 14:26 开始时一致（0A `FF 0F 00 00`、0B `FF FF 00 00`），无残留副作用。

---

## 五、验证结果（全绿）

| 项 | 结果 |
|---|---|
| 本地 `python -m compileall` + 7 组 stub 时序单测 | 全过：重载挂起、启动期不误写继电器、从站上线自动补同步、unavailable 重试、灯帧去重/继电器不去重、稳定后一次按键各 1 帧、有限放弃 + stop 取消任务 |
| HA 容器内 import | `RECENT_FRAMES=200`、`SETTLE=2.0`、`RETRY=(0.5,1.0,2.0)`、`DEDUPE=0.3`、`PROTOCOLS=['clowire','flk','lf','symi']` |
| `python -m homeassistant --script check_config -c /config` | 退出码 0 |
| `docker restart homeassistant` | HTTP 200（约 10s），无 Traceback / ImportError |
| 启动期 | 写线圈帧 **0**、`not currently available` WARNING **0**；日志出现 `waits for N entity/entities to become available` |
| logger 生效 | 日志出现 `Sent 8 byte(s): 0a 01 ...`、`Read 9 byte(s): ...`、`skips duplicate LED write ...` |
| diagnostics 实测 | `master.lines = 200 frames`（原 40 上限已突破） |
| **最终重载验收** | 恢复 6 路后 bitmask `FF 0F` / `FF FF`；再 reload 一次，6 个实体仍全 on、bitmask 不变、无关帧、WARNING 0 |

---

## 六、补丁包与部署到其它服务器

交付包：`D:/AI工具/workbuddy/2026-11-06-09-57-35/symi_modbus_修复补丁_20261106.tgz`

### ⚠️ 不能「上传后直接解压覆盖」

早期包版本里放着 `symi_modbus/` 目录和**整份** `configuration.yaml`，直接用会踩四个坑：

| # | 坑 | 后果 |
|---|---|---|
| 1 | 包内 `symi_modbus/` 是**源码目录名**，目标是 `custom_components/symi_modbus/` | 直接解压到 config 目录会放错位置，文件根本不生效 |
| 2 | 整份 `configuration.yaml` 是 **casaos25 本机**的，含 `default_config:`、`frontend: !include_dir_merge_named themes`、三个 `!include` | 覆盖会抹掉目标机所有配置。典型反例：**casaos24 定制镜像精简掉了 `default_config`，`configuration.yaml` 必须手写 `webhook:` 才有 `/api/webhook/*`**（米家集成依赖），一覆盖米家立刻挂 |
| 3 | Python 代码 + logger 都要**重启 HA** 才生效 | 只传文件不重启，看起来像没生效 |
| 4 | 本包**只含修复，不含 FLK 品牌适配** | 目标机若是干净旧版集成，传完不会出现 FLK 品牌选项；需要另传 `symi_modbus_FLK补丁_20261106.tgz` |

### 现在包里有什么（已改成安全版）

```
deploy.sh                      # 幂等部署脚本：备份 → 放文件 → 合并 logger → check_config → 重启 → 等 HTTP 200
symi_modbus/linkage.py
symi_modbus/connection.py
logger.snippet.yaml            # 只含 logger 段，供已有 logger: 的机器手工合并
README.txt                     # 用法与注意事项
```

**整份 `configuration.yaml` 已从包里移除**，只剩增量片段，避免误覆盖。

### 部署步骤（目标机 SSH）

```sh
# 1) 上传
scp symi_modbus_修复补丁_20261106.tgz symi@<目标机IP>:/tmp/

# 2) 解压并部署；参数 = 目标机 HA 配置根目录
ssh symi@<目标机IP>
tar xzf /tmp/symi_modbus_修复补丁_20261106.tgz -C /tmp/symi_fix
sudo sh /tmp/symi_fix/deploy.sh /DATA/AppData/homeassistant/config
```

`deploy.sh` 会：校验集成目录存在 → 备份原文件（固定后缀 `.bak-fix-20261106`，**已存在则不覆盖**，重复执行也不会把原始版冲掉）→ 装两个 `.py` → **纯文本**追加 logger 段（若目标已有 `logger:` 段则不自动改，打印片段让人工合并）→ `check_config`（不通过就中止、不重启）→ `docker restart homeassistant` → 等 HTTP 200。

路径因机器而异：casaos25 是 `/DATA/AppData/homeassistant/config`；纯 Docker 部署可能是 `/homeassistant/config` 或 compose 里挂载的卷，用 `docker inspect homeassistant --format '{{json .Mounts}}'` 确认。

### 验收（部署后）

```sh
docker exec -e PYTHONPATH=/config homeassistant python -c \
  "from custom_components.symi_modbus import linkage, connection; print(connection.RECENT_FRAMES, linkage.STARTUP_SETTLE_WINDOW)"
# 期望输出: 200 2.0
docker logs --since 2m homeassistant 2>&1 | grep -E 'Sent 8 byte|waits for|skips duplicate'
docker logs --since 2m homeassistant 2>&1 | grep -ic 'not currently available'   # 期望 0
```

### 适用性边界

- 前提：目标机**已安装** `symi_modbus` 集成（本包不是全量集成）。
- `linkage.py` 是**整份重写**，会覆盖目标机对该文件的任何自定义改动 —— 部署前先看脚本生成的备份，必要时先 diff。
- 与品牌适配无耦合：不含 FLK 也能正常工作，但 FLK 品牌需另一个补丁包。
- 若是 `192.168.2.61` 本机：**已经部署完成，不需要再传**；脚本幂等，重复跑也无害。

---

## 七、交付物

| 文件 | 说明 |
|---|---|
| `symi_modbus_修复补丁_20261106.tgz` | 3 个改动文件 + 部署脚本 + logger 片段 |
| `symi_modbus_FLK补丁_20261106.tgz` | 上一轮的 FLK 品牌补丁（**独立，需单独部署**） |
| `symi_modbus_485抓帧.py` | 容器内读 diagnostics 总线帧；文档已同步 40→200 帧、窗口 10s→1~2 分钟；支持 `--toggle <实体ID>` |
| `验证_flk.py` | FLK 集成容器内回归脚本 |
| `K7x开关面板_MODBUS调试记录.md` | K7x/FLK 协议抓包与全地址码表 |
| `symi_modbus_修复操作记录_20261106.md` | **本文件** |

## 八、遗留

1. 清单 8「总线上疑似第二写入源」本次未复查。以后再出现「明明发了却控制不了」，优先查 A/B 接线（ttyS0 继电器与 ttyS1 面板是否共用同一条线）以及现场有没有串口调试助手/上位机同时在发帧 —— 多主站同时写会互相覆盖。
2. 2/3/5 三项按用户决定保持原样，实际落地时自行在 UI 改名称与实体数量。

## 九、合并到仓库 2.6.11（2026-11-06）

四项修复复核后按增量合并，未整份覆盖：

| 项 | 处理 |
|---|---|
| `RECENT_FRAMES` 40 → 200 | 已合入 `connection.py` |
| 联动写入 unavailable 重试 | 已合入 `linkage.py`（0.5 / 1.0 / 2.0 秒） |
| 灯帧 0.3 秒去重 | 已合入 `linkage.py` |
| 启动 / 按键写面板灯 | **未合入**：本机两块面板共用一条 485 总线、设备地址都是 `01`，主机灯帧会被所有面板执行。2.6.11 保持“按键/启动不写面板灯”，面板自己点灯。 |
| logger 片段 | 属于 `configuration.yaml`，不进集成仓库 |
| FLK 品牌 | 本补丁不含，未合入 2.6.11 |

验证：170 个单测通过；本机 HA `2026.10.2` 部署 `2.6.11` 后 `check_config` 通过、重启 3 秒 HTTP 200、无 ERROR；
`scripts/verify_load.py` 场景二 100 开关（4 从站 × 32 线圈）、场景三 400 按钮（50 面板 × 8 键）通过。

## 十、FLK 品牌合并到 2.6.12（2026-11-06）

从 casaos25（`192.168.2.61`）拉取 FLK 接入的 4 个文件，按增量合并：

- 新增 `panels/flk.py`（6073 B，与记录一致）。
- `const.py` 加 `BRAND_FLK`；casaos25 版本把 `DEFAULT_LED_FRAME_TYPE` 改回 `SET`，**未采纳**，保留 2.6.11 的 `REPORT`。
- `panels/__init__.py` 注册 `FlkProtocol`。
- `config_flow.py` 下拉加 `FLK (弗雷克)`。
- 新增 `tests/test_flk.py`：整包解析、8 键寄存器、分片续接、坏字节重同步、写灯帧/长按松开忽略、坏 CRC、mask 叠加。

验证：180 个单测通过；本机 HA `2026.10.2` `check_config` 通过，`PROTOCOLS=['symi','clowire','lf','flk']`、`panel_keys('flk')=8`、下拉含 `flk`；重启 3 秒 HTTP 200，ERROR/Traceback/ImportError 0。
