# HIFA Course Grabber

湖北美术学院选课系统单课抢课脚本。

这个仓库当前只包含单课版脚本：

- `grab_course.py`：手动登录后，按关键词搜索课程并持续重试抢课
- `使用教程.md`：详细使用说明

## 环境准备

```bash
python3 -m pip install playwright
python3 -m playwright install chromium
```

## 运行方式

```bash
cd ~/Desktop/抢课脚本
python3 grab_course.py
```

## 使用流程

1. 启动脚本后，在弹出的浏览器中手动登录。
2. 回到终端按回车。
3. 输入课程名或教师名关键词搜索。
4. 选择目标课程。
5. 脚本会在开放时间后持续重试，直到成功或手动停止。

## 运行前建议确认

打开 `grab_course.py`，检查以下参数是否正确：

- `BATCH_ID`
- `BATCH_BEGIN`
- `RETRY_INTERVAL`

## 停止脚本

```bash
Ctrl + C
```

## 说明

- 本项目只用于正常权限和开放时间内的操作加速。
- 最终选课结果以教务系统显示为准。
- 详细说明见 `使用教程.md`。
