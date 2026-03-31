#!/usr/bin/env python3
"""
抢课脚本 - 湖北美术学院选课系统
使用方法:
  1. 运行脚本: python3 grab_course.py
  2. 在弹出的浏览器窗口中手动登录
  3. 登录成功后回到终端按回车
  4. 输入要抢的课程关键词（课程名或教师名）
  5. 从搜索结果中选择目标课程
  6. 脚本自动开始抢课（在选课窗口开放前可提前运行，会自动等待）
"""

import asyncio
import sys
from datetime import datetime
from playwright.async_api import async_playwright

BASE_URL = "https://xjwxk.hifa.edu.cn/xsxk"
BATCH_ID = "1b380a657c11450aa9dc99586618643b"
# 选课窗口开放时间: 2026-03-31 12:00:00
BATCH_BEGIN = "2026-03-31 12:00:00"
RETRY_INTERVAL = 0.5   # 抢课重试间隔（秒）
SEARCH_PAGE_SIZE = 100
RATE_LIMIT_COOLDOWN = 5.0
HTML_RESPONSE_COOLDOWN = 8.0


# /elective/clazz/list 需要 JSON，其他接口用 form-encoded
JSON_URLS = ["/elective/clazz/list"]


async def api_post(page, path, data=None):
    if data is None:
        data = {}
    use_json = any(u in path for u in JSON_URLS)
    result = await page.evaluate(
        r"""async ([path, data, useJson]) => {
            let body, contentType;
            if (useJson) {
                body = JSON.stringify(data);
                contentType = 'application/json;charset=UTF-8';
            } else {
                body = Object.keys(data)
                    .map(k => encodeURIComponent(k) + '=' + encodeURIComponent(data[k]))
                    .join('&');
                contentType = 'application/x-www-form-urlencoded';
            }
            try {
                const resp = await fetch(path, {
                    method: 'POST',
                    headers: {
                        'Content-Type': contentType,
                        'Authorization': sessionStorage.getItem('token') || ''
                    },
                    body: body
                });
                const responseUrl = resp.url;
                const httpStatus = resp.status;
                const responseType = resp.headers.get('content-type') || '';
                const text = await resp.text();
                const bodyPreview = text.replace(/\s+/g, ' ').trim().slice(0, 200);

                if (responseType.includes('application/json')) {
                    try {
                        return JSON.parse(text);
                    } catch (e) {
                        return {
                            code: -1,
                            msg: `JSON 解析失败: ${e.toString()}`,
                            httpStatus,
                            responseUrl,
                            contentType: responseType,
                            bodyPreview
                        };
                    }
                }

                return {
                    code: -1,
                    msg: responseType.includes('text/html')
                        ? '接口返回 HTML 页面而不是 JSON'
                        : `接口返回非 JSON 内容: ${responseType || 'unknown'}`,
                    httpStatus,
                    responseUrl,
                    contentType: responseType,
                    bodyPreview
                };
            } catch(e) {
                return {code: -1, msg: e.toString()};
            }
        }""",
        [path, data, use_json]
    )
    return result


async def search_courses(page, keyword, clazz_type="XGKC"):
    print(f"\n正在搜索课程: {keyword} ...")
    # 先按课程名搜索
    data = {
        "batchId": BATCH_ID,
        "teachingClassType": clazz_type,
        "pageNumber": 1,
        "pageSize": SEARCH_PAGE_SIZE,
        "KCM": keyword,
    }
    result = await api_post(page, f"{BASE_URL}/elective/clazz/list", data)
    rows = []
    if result and result.get("code") == 200:
        rows = result.get("data", {}).get("rows", []) or []

    # 若无结果，按教师名搜索
    if not rows:
        data2 = {
            "batchId": BATCH_ID,
            "teachingClassType": clazz_type,
            "pageNumber": 1,
            "pageSize": SEARCH_PAGE_SIZE,
            "JSM": keyword,
        }
        result2 = await api_post(page, f"{BASE_URL}/elective/clazz/list", data2)
        if result2 and result2.get("code") == 200:
            rows = result2.get("data", {}).get("rows", []) or []
    return rows


def describe_access_issue(code, msg):
    reason_map = {
        401: "接口返回未登录或 token 已失效",
        402: "当前登录状态不可用于该接口，可能需要重新进入选课页或重新登录",
        403: "接口拒绝访问，这不一定是登录过期，也可能是未到开放时间、批次不匹配或当前账号无权限",
    }
    reason = reason_map.get(code, "接口返回了访问限制错误")
    if msg:
        return f"{reason}；服务端消息：{msg}"
    return reason


def is_rate_limited(code, msg):
    text = str(msg or "")
    return code == 403 and "请求过快" in text


def is_html_response(result):
    if not result:
        return False
    if result.get("code") != -1:
        return False
    content_type = str(result.get("contentType") or "").lower()
    preview = str(result.get("bodyPreview") or "").lower()
    msg = str(result.get("msg") or "")
    return (
        "html" in content_type
        or preview.startswith("<!doctype")
        or preview.startswith("<html")
        or "html 页面而不是 json" in msg
    )


def display_courses(courses):
    if not courses:
        print("未找到课程")
        return
    print(f"\n找到 {len(courses)} 门课程:")
    print(f"{'序号':<4} {'课程名':<22} {'教师':<12} {'时间/地点':<22} {'余量':<6} JXBID")
    print("-" * 95)
    for i, c in enumerate(courses):
        name = (c.get("KCM") or "")[:20]
        teacher = (c.get("JSM") or "")[:10]
        time_str = (c.get("YPSJMS") or "")[:20]
        remaining = c.get("KYS", "?")
        jxbid = c.get("JXBID", "")
        print(f"{i+1:<4} {name:<22} {teacher:<12} {time_str:<22} {remaining:<6} {jxbid}")


async def add_course(page, course, clazz_type="XGKC"):
    data = {
        "clazzType": clazz_type,
        "clazzId": course["JXBID"],
        "secretVal": course.get("secretVal") or "",
        "batchId": BATCH_ID,
        "needBook": "",
    }
    return await api_post(page, f"{BASE_URL}/elective/clazz/add", data)


async def wait_until_open():
    target = datetime.strptime(BATCH_BEGIN, "%Y-%m-%d %H:%M:%S")
    now = datetime.now()
    if now >= target:
        return
    diff = (target - now).total_seconds()
    print(f"\n选课窗口尚未开放，将在 {BATCH_BEGIN} 开始")
    print(f"距开放还有 {int(diff//3600)} 小时 {int((diff%3600)//60)} 分 {int(diff%60)} 秒")
    print("脚本将自动等待并在开放时立即发起请求...")
    while True:
        remaining = (target - datetime.now()).total_seconds()
        if remaining <= 0.1:
            break
        if remaining > 60:
            await asyncio.sleep(10)
        elif remaining > 5:
            await asyncio.sleep(1)
        else:
            await asyncio.sleep(0.05)
    print("选课窗口已开放！立即开始抢课...")


async def handle_rate_limit(page, ts, attempt, course_name, teacher_name, msg):
    print(
        f"[{ts}] 第{attempt}次 请求被限流 | {course_name} / {teacher_name} | {msg}"
    )
    print(
        f"系统提示请求过快，脚本将冷却 {RATE_LIMIT_COOLDOWN:.1f} 秒后刷新选课页并继续。"
    )
    await asyncio.sleep(RATE_LIMIT_COOLDOWN)
    await page.goto(f"{BASE_URL}/elective/grablessons?batchId={BATCH_ID}")
    await page.wait_for_load_state("networkidle")
    await asyncio.sleep(1)


async def handle_html_response(page, ts, attempt, course_name, teacher_name, result):
    http_status = result.get("httpStatus")
    response_url = result.get("responseUrl") or "未知地址"
    content_type = result.get("contentType") or "unknown"
    preview = result.get("bodyPreview") or ""
    print(
        f"[{ts}] 第{attempt}次 接口返回了 HTML/非 JSON | {course_name} / {teacher_name}"
    )
    print(
        f"HTTP={http_status} | Content-Type={content_type} | URL={response_url}"
    )
    if preview:
        print(f"响应预览: {preview}")
    print(
        f"这通常表示跳到了登录页、风控页或网关错误页。脚本将冷却 {HTML_RESPONSE_COOLDOWN:.1f} 秒后刷新选课页再继续。"
    )
    await asyncio.sleep(HTML_RESPONSE_COOLDOWN)
    await page.goto(f"{BASE_URL}/elective/grablessons?batchId={BATCH_ID}")
    await page.wait_for_load_state("networkidle")
    await asyncio.sleep(1)


async def close_context_safely(context):
    if context is None:
        return
    try:
        await context.close()
    except Exception:
        pass


async def main():
    context = None
    interrupted = False
    try:
        async with async_playwright() as p:
            print("启动浏览器（使用持久化配置，避免重复登录）...")
            context = await p.chromium.launch_persistent_context(
                user_data_dir="/tmp/xsxk_browser_profile",
                headless=False,
                args=["--ignore-certificate-errors"],
            )

            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(f"{BASE_URL}/profile/index.html")

            print("\n请在浏览器中手动完成登录")
            print("登录成功后，回到此终端按回车继续...")
            input()

            # 检测登录 token
            token = await page.evaluate("() => sessionStorage.getItem('token')")
            if not token:
                print("未检测到 token，等待登录完成（最多30秒）...")
                for _ in range(30):
                    await asyncio.sleep(1)
                    token = await page.evaluate("() => sessionStorage.getItem('token')")
                    if token:
                        break

            if not token:
                print("错误：未能获取登录 token，请确认已成功登录后重新运行")
                return

            print(f"登录成功！Token: {token[:20]}...")

            # 跳转到选课页面
            await page.goto(f"{BASE_URL}/elective/grablessons?batchId={BATCH_ID}")
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(1)

            # 选择目标课程
            target_course = None
            while target_course is None:
                keyword = input("\n请输入要抢的课程关键词（课程名或教师名）: ").strip()
                if not keyword:
                    continue

                courses = await search_courses(page, keyword)
                display_courses(courses)

                if not courses:
                    again = input("未找到课程，重新搜索？(y/n): ").strip().lower()
                    if again != 'y':
                        return
                    continue

                choice = input(
                    f"\n请输入课程序号 (1-{len(courses)})，或输入 s 重新搜索: "
                ).strip()
                if choice.lower() == 's':
                    continue
                try:
                    idx = int(choice) - 1
                    if 0 <= idx < len(courses):
                        target_course = courses[idx]
                    else:
                        print("序号超出范围")
                except ValueError:
                    print("请输入有效序号")

            course_name = target_course.get("KCM", "未知")
            teacher_name = target_course.get("JSM", "")
            print(f"\n目标课程: {course_name} / {teacher_name}")
            print(f"JXBID: {target_course.get('JXBID')}")
            print(f"secretVal: {target_course.get('secretVal', '（空）')}")

            # 等待选课窗口
            await wait_until_open()

            # 抢课主循环
            attempt = 0
            success = False
            print(f"\n开始抢课，间隔 {RETRY_INTERVAL}s，按 Ctrl+C 停止")
            print("=" * 50)

            while not success:
                attempt += 1
                ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                result = await add_course(page, target_course)
                code = result.get("code") if result else None
                msg = (result.get("msg") or "") if result else "无响应"

                if code == 200:
                    print(f"[{ts}] 第{attempt}次 ✓ 抢课成功！已进入选课队列")
                    success = True
                elif code == 301:
                    # 服务端要求二次确认
                    print(f"[{ts}] 第{attempt}次 需确认: {msg}")
                    confirm = input("是否确认选课？(y/n): ").strip().lower()
                    if confirm == 'y':
                        r2 = await add_course(page, target_course)
                        if r2 and r2.get("code") == 200:
                            print("确认成功！")
                            success = True
                        else:
                            print(f"确认失败: {r2}")
                elif is_rate_limited(code, msg):
                    await handle_rate_limit(
                        page, ts, attempt, course_name, teacher_name, msg
                    )
                elif is_html_response(result):
                    await handle_html_response(
                        page, ts, attempt, course_name, teacher_name, result
                    )
                elif code in (401, 402, 403):
                    token_exists = await page.evaluate(
                        "() => Boolean(sessionStorage.getItem('token'))"
                    )
                    print(
                        f"[{ts}] 第{attempt}次 请求被拒绝 | {course_name} / {teacher_name} "
                        f"| code={code}: {msg}"
                    )
                    print(f"原因判断: {describe_access_issue(code, msg)}")
                    print(
                        f"浏览器 sessionStorage token 状态: {'存在' if token_exists else '缺失'}"
                    )
                    print("建议: 重新确认已进入学生主页和选课页，再重新运行脚本。")
                    break
                else:
                    print(f"[{ts}] 第{attempt}次 失败 (code={code}): {msg}")
                    await asyncio.sleep(RETRY_INTERVAL)

            if success:
                print("\n抢课请求已提交！请在浏览器中查看选课结果。")

            input("按回车关闭浏览器...")
    except KeyboardInterrupt:
        interrupted = True
        print("\n已手动停止，正在关闭浏览器...")
    finally:
        await close_context_safely(context)


if __name__ == "__main__":
    asyncio.run(main())
