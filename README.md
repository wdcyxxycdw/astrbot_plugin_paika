# AstrBot 排卡插件

`paika` 是一个面向 AstrBot + OneBot v11/NapCat 的群聊组队插件。

## 运行环境

- AstrBot `>=4.25.0,<5`
- Python 3.9+
- OneBot v11 适配器（推荐 aiocqhttp）
- NapCat reaction 需要 NapCat 支持 `set_msg_emoji_like` 和对应 reaction notice

## 功能

- 一个群可以同时存在多个排卡房间。
- 同一用户在同一个群内同时只能加入一个未结束房间，不同群互不影响。
- 房主发送 `@机器人 /排卡 [人数] [房间标题]` 开房，房主自动占一个名额，等待中房主不能下车。
- `/查房` 查看当前群的等待中/已发车房间。
- `/上车`、`/下车`、`/发车`、`/结束` 使用 AstrBot 原生斜杠指令；多房间时可填写房间标题。
- 不带斜杠的自然语言可以由 LLM 调用排卡工具处理。
- 回复排卡消息发送 `上车`、`下车` 或 `发车` 时，可以省略房间标题，Reply 入口保持确定性处理。
- 满员自动发车；发车后成员状态锁定，不允许上车或下车，房主仍可使用 `/结束`。
- 状态变化、reaction 操作、定时提醒和自动结束都会发送格式化通知，并以 At 形式列出当前房间成员。
- 等待中的房间默认 5 分钟提醒一次，创建后默认 15 分钟未发车自动解散；已发车房间从发车时间起超过同一配置自动结束，填 0 可关闭。
- NapCat 原生 emoji reaction 作为可选增强；即使 reaction 不可用，Reply 和斜杠指令仍然可用。

人数包含房主。例如 `/排卡 4 周末开黑` 表示总人数上限为 4 人，其中房主已经占 1 席。

## 指令

```text
/排卡 [人数] [房间标题]
/查房
/上车 [房间标题]
/下车 [房间标题]
/发车 [房间标题]
/结束 [房间标题]
```

不带斜杠的自然语言由 AstrBot 的 LLM Tool 判断后调用排卡业务；Reply 和 reaction 仍然由插件的确定性事件入口处理。没有房间标题时，插件只会在当前群只有一个候选房间时自动选择；有多个房间时请回复对应的开房消息、点击对应消息上的表情，或填写房间名称。发车后成员状态锁定，房主仍可使用 `/结束` 结束房间。

## 配置

插件配置页支持以下主要选项：

- `default_capacity`：未指定人数时的默认人数，范围 2–100。
- `max_capacity`：单个房间允许的最大人数，范围 2–100。
- `default_content`：未指定标题时的默认标题。
- `reaction_enabled`：是否启用 NapCat 原生 reaction。
- `reaction_emoji_id` / `reaction_emoji_type`：NapCat reaction 参数。
- `show_ended_in_list`：`/查房` 是否显示已结束房间。
- `auto_disband_minutes`：waiting 房间自动解散、started 房间自动结束的时间，0 表示关闭，范围 0–1440。
- `reminder_minutes`：waiting 房间提醒间隔，0 表示关闭，范围 0–1440。

生产数据默认写入 AstrBot 的：

```text
data/plugin_data/paika/paika.db
```

## 安装

在 AstrBot WebUI 的插件管理中使用“从链接安装”，填写：

```text
https://github.com/wdcyxxycdw/astrbot_plugin_paika
```

也可以将源码放入 `data/plugins/astrbot_plugin_paika`，然后在 AstrBot 中加载插件。插件不需要额外运行时依赖，AstrBot 提供插件 API。请先配置并连接 OneBot v11（`aiocqhttp`）适配器；reaction 功能还需要 NapCat 支持。

## NapCat reaction 注意事项

AstrBot 当前没有统一的 OneBot 原生 reaction API，因此插件会直接尝试调用 NapCat 的 `set_msg_emoji_like`。`reaction_emoji_id` 默认设置为 `76`，不同 NapCat/QQ 版本可能需要在插件配置中调整。插件会从 raw notice 读取 `group_msg_emoji_like` 的目标消息 ID、`likes` 和 `is_add` 字段；真实环境仍需确认发送消息 ID 与 reaction notice 中的 ID 一致。

## 兼容性与已知限制

- 插件声明兼容 AstrBot `>=4.25.0,<5`；已在 AstrBot 4.28.1 容器验证加载、工具注册和真实消息组件解析，并非对所有版本逐一验收。
- 本地回归测试通过；完整真人 QQ 群聊验收暂缓，不保证所有 QQNT / NapCat 版本的 reaction 行为一致。
- 正常 OneBot 发送会保存开房消息 ID。兼容发送路径若无法返回 ID，房间仍可通过标题操作，但不能保证 Reply / reaction 精确选房。
- 房间仅用标题展示，数据库内部仍保留编号；纯数字操作参数保留旧编号兼容语义，建议使用非纯数字标题。
- NapCat 属于第三方 QQ 接入方案，存在被 QQ 踢下线或限制账号的可能。建议使用专用账号；本插件无法解除 QQ 风控或自动完成扫码登录。
- SQLite 会在本地保存群号、成员 QQ 标识、昵称、房间信息和操作时间；插件自身不上传这些数据。请勿公开运行配置和数据库。

问题反馈：[GitHub Issues](https://github.com/wdcyxxycdw/astrbot_plugin_paika/issues)。反馈时请隐去账号标识、密码和令牌。

## 本地测试

开发测试依赖：

```bash
python -m pip install -r requirements-dev.txt
```

测试和编译检查：

```bash
python -m pytest -q
python -m compileall -q main.py paika tests
```

## 许可证

本项目使用 MIT License，详见 [LICENSE](LICENSE)。
