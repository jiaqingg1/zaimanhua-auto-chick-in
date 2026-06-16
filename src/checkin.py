import os
import time
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv
from utils import extract_user_info_from_cookies, claim_task_reward, get_task_list, extract_tasks_from_response, init_localstorage

# 配置
MAX_RETRIES = 5
PAGE_TIMEOUT = 60000  # 60秒
CHECKIN_TASK_ID = 8  # "到此一游"签到任务
VIP_TASK_ID = 16     # "VIP福利"每日领取任务


def _make_account_label(default_label, cookie_str):
    """从 Cookie 中提取用户名，生成带用户名的账号标签"""
    try:
        user_info = extract_user_info_from_cookies(cookie_str)
        if isinstance(user_info, dict):
            name = user_info.get('nickname') or user_info.get('username')
            if name:
                return f"{default_label} ({name})"
    except Exception:
        pass
    return default_label


def get_all_cookies():
    """获取所有账号的 Cookie"""
    load_dotenv()  # 自动加载 .env 文件（本地测试用）

    cookies_list = []

    # 兼容单账号配置
    single = os.environ.get('ZAIMANHUA_COOKIE')
    if single:
        label = _make_account_label('默认账号', single)
        cookies_list.append((label, single))

    # 支持多账号配置 ZAIMANHUA_COOKIE_1, _2, _3...
    i = 1
    while True:
        cookie = os.environ.get(f'ZAIMANHUA_COOKIE_{i}')
        if cookie:
            label = _make_account_label(f'账号 {i}', cookie)
            cookies_list.append((label, cookie))
            i += 1
        else:
            break

    return cookies_list


def parse_cookies(cookie_str):
    """解析 Cookie 字符串为 Playwright 格式"""
    cookies = []
    for item in cookie_str.split(';'):
        item = item.strip()
        if '=' in item:
            name, value = item.split('=', 1)
            cookies.append({
                'name': name.strip(),
                'value': value.strip(),
                'domain': '.zaimanhua.com',
                'path': '/'
            })
    return cookies


def claim_checkin_reward(cookie_str):
    """领取签到任务（到此一游）的积分奖励"""
    user_info = extract_user_info_from_cookies(cookie_str)
    token = user_info.get('token') if isinstance(user_info, dict) else None

    if not token:
        print("无法获取 token，跳过领取积分")
        return False

    # 获取任务列表，检查签到任务状态
    task_result = get_task_list(token)
    if not task_result or task_result.get('errno') != 0:
        print("获取任务列表失败")
        return False

    tasks = extract_tasks_from_response(task_result)
    for task in tasks:
        task_id = task.get('id') or task.get('taskId')
        task_name = task.get('title') or task.get('name') or task.get('taskName', '未知')
        status = task.get('status', 0)

        if task_id == CHECKIN_TASK_ID:
            # status=2 表示可领取
            if status == 2:
                print(f"发现可领取任务: {task_name} (ID: {task_id})")
                success, result = claim_task_reward(token, task_id)
                if success:
                    print(f"  [OK] 积分领取成功！")
                    return True
                else:
                    print(f"  [FAIL] 积分领取失败: {result}")
                    return False
            elif status == 3:
                print(f"签到任务积分已领取: {task_name}")
                return True
            else:
                print(f"签到任务未完成: {task_name} (status={status})")
                return False

    print(f"未找到签到任务 (ID={CHECKIN_TASK_ID})")
    return False


def claim_vip_reward(cookie_str):
    """领取VIP福利的每日积分奖励"""
    user_info = extract_user_info_from_cookies(cookie_str)
    token = user_info.get('token') if isinstance(user_info, dict) else None

    if not token:
        print("无法获取 token，跳过VIP福利领取")
        return False

    # 获取任务列表，检查VIP福利任务状态
    task_result = get_task_list(token)
    if not task_result or task_result.get('errno') != 0:
        print("获取任务列表失败")
        return False

    tasks = extract_tasks_from_response(task_result)
    for task in tasks:
        task_id = task.get('id') or task.get('taskId')
        task_name = task.get('title') or task.get('name') or task.get('taskName', '未知')
        status = task.get('status', 0)

        if task_id == VIP_TASK_ID:
            if status == 2:
                print(f"发现可领取任务: {task_name} (ID: {task_id})")
                success, result = claim_task_reward(token, task_id)
                if success:
                    print(f"  [OK] VIP福利领取成功！")
                    return True
                else:
                    print(f"  [FAIL] VIP福利领取失败: {result}")
                    return False
            elif status == 3:
                print(f"VIP福利已领取: {task_name}")
                return True
            elif status == 1:
                print(f"VIP福利不可领取（非VIP或未满足条件）: {task_name}")
                return False
            else:
                print(f"VIP福利状态未知: {task_name} (status={status})")
                return False

    print(f"未找到VIP福利任务 (ID={VIP_TASK_ID})，可能非VIP账号")
    return False


def checkin_once(cookie_str):
    """执行一次签到尝试"""
    cookies = parse_cookies(cookie_str)
    print(f"已解析 {len(cookies)} 个 Cookie")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        context.add_cookies(cookies)

        page = context.new_page()
        page.set_default_timeout(PAGE_TIMEOUT)

        try:
            # 先访问首页设置localStorage（关键：避免直接跳转到登录页）
            print("访问首页设置localStorage...")
            page.goto('https://www.zaimanhua.com/', wait_until='domcontentloaded', timeout=30000)
            page.wait_for_timeout(3000)
            
            # 设置localStorage确保Vue应用识别登录状态
            print("设置localStorage...")
            try:
                init_localstorage(page, cookie_str)
            except Exception as e:
                print(f"设置localStorage失败: {e}")
            
            # 等待localStorage生效
            page.wait_for_timeout(1000)
            
            # 访问用户中心进行签到
            print("访问用户中心...")
            page.goto('https://i.zaimanhua.com/', timeout=PAGE_TIMEOUT, wait_until='domcontentloaded')
            
            # 等待页面稳定（多重等待策略）
            print("等待页面加载...")
            try:
                page.wait_for_load_state('networkidle', timeout=30000)
            except:
                print("networkidle超时，尝试domcontentloaded")
                page.wait_for_load_state('domcontentloaded', timeout=10000)
            
            # 额外等待确保Vue应用渲染完成
            print("等待Vue应用渲染...")
            page.wait_for_timeout(3000)
            
            print(f"页面标题: {page.title()}")

            # 多次尝试等待按钮加载
            print("等待按钮加载...")
            button_found = False
            for attempt in range(3):
                try:
                    page.wait_for_selector('button.ant-btn-primary', timeout=10000)
                    button_found = True
                    print(f"按钮已加载（第{attempt+1}次尝试）")
                    break
                except:
                    print(f"第{attempt+1}次等待按钮超时，继续尝试...")
                    if attempt < 2:
                        page.wait_for_timeout(2000)
            
            if not button_found:
                print("按钮加载等待失败，继续尝试查找...")

            # 查找所有 .ant-btn-primary 按钮
            print("查找签到按钮...")
            
            # 尝试多种选择器策略
            selectors_to_try = [
                'button.ant-btn-primary',
                'button.ant-btn',
                '.ant-btn-primary',
                'button'
            ]
            
            buttons_locator = None
            buttons_count = 0
            
            for selector in selectors_to_try:
                try:
                    locator = page.locator(selector)
                    count = locator.count()
                    if count > 0:
                        buttons_locator = locator
                        buttons_count = count
                        print(f"使用选择器 '{selector}' 找到 {buttons_count} 个按钮")
                        break
                except Exception as e:
                    print(f"选择器 '{selector}' 失败: {e}")
            
            if buttons_count == 0:
                print("[ERROR] 未找到任何按钮")
                page.screenshot(path="error_no_buttons_at_all.png")
                return False

            checkin_button = None
            button_text = None
            
            # 遍历所有按钮，查找包含签到文字的
            for i in range(buttons_count):
                if not buttons_locator:
                    continue
                try:
                    btn = buttons_locator.nth(i)
                    text = btn.inner_text()
                    print(f"  按钮 {i}: 文字='{text}'")
                    
                    if '立即签到' in text or '签到' in text or '已签到' in text:
                        checkin_button = btn
                        button_text = text
                        print(f"匹配到签到按钮: '{text}'")
                        break
                except Exception as e:
                    print(f"  按钮 {i}: 获取文字失败 - {e}")

            if not checkin_button:
                print("[ERROR] 未找到签到按钮")
                page.screenshot(path="error_no_button.png")
                return False

            if not button_text:
                print("[ERROR] 无法获取按钮文字")
                page.screenshot(path="error_no_text.png")
                return False

            is_disabled = checkin_button.is_disabled()
            print(f"按钮禁用状态: {is_disabled}")

            # 如果找到的是"已签到"按钮，直接返回成功
            if "已签到" in button_text:
                print("今天已经签到过了！")
                return True

            # 点击签到按钮
            print("点击签到按钮...")
            checkin_button.click()

            # 等待1秒后刷新页面验证
            print("等待 1 秒后刷新页面验证...")
            page.wait_for_timeout(1000)
            page.reload(wait_until='domcontentloaded')
            
            # 等待页面稳定
            try:
                page.wait_for_load_state('networkidle', timeout=30000)
            except:
                page.wait_for_load_state('domcontentloaded', timeout=10000)
            
            page.wait_for_timeout(2000)

            # 验证是否签到成功（查找"已签到"按钮）
            print("验证签到状态...")
            try:
                # 多种选择器尝试
                for selector in ['button:has-text("已签到")', 'button.ant-btn-primary', '.ant-btn']:
                    try:
                        signed_locator = page.locator(selector)
                        if signed_locator.count() > 0:
                            for i in range(signed_locator.count()):
                                btn = signed_locator.nth(i)
                                text = btn.inner_text()
                                if "已签到" in text:
                                    button_text = text
                                    is_disabled = btn.is_disabled()
                                    print(f"刷新后按钮文字: {button_text}")
                                    print(f"刷新后按钮禁用状态: {is_disabled}")
                                    print("✓ 签到成功！按钮已变为'已签到'")
                                    return True
                    except:
                        continue
            except Exception as e:
                print(f"验证签到状态时出错: {e}")

            # 如果没有找到"已签到"，可能签到失败
            print("[WARN] 未确认到签到成功状态，截图保存...")
            page.screenshot(path="error_verify_failed.png")
            return False

        except Exception as e:
            print(f"签到失败: {e}")
            try:
                page.screenshot(path="error_screenshot.png")
                print("已保存错误截图: error_screenshot.png")
            except:
                pass
            return False
        finally:
            browser.close()


def checkin(cookie_str):
    """执行签到，带重试机制"""
    for attempt in range(1, MAX_RETRIES + 1):
        print(f"尝试第 {attempt}/{MAX_RETRIES} 次...")
        try:
            if checkin_once(cookie_str):
                return True
        except Exception as e:
            print(f"第 {attempt} 次尝试出错: {e}")

        if attempt < MAX_RETRIES:
            wait_time = attempt * 10  # 递增等待时间
            print(f"等待 {wait_time} 秒后重试...")
            time.sleep(wait_time)

    print(f"已重试 {MAX_RETRIES} 次，签到失败")
    return False


def main():
    """主函数，支持多账号签到"""
    cookies_list = get_all_cookies()

    if not cookies_list:
        print("Error: 未配置任何账号 Cookie")
        print("请设置 ZAIMANHUA_COOKIE 或 ZAIMANHUA_COOKIE_1, ZAIMANHUA_COOKIE_2 等环境变量")
        return False

    print(f"共发现 {len(cookies_list)} 个账号")

    all_success = True
    for name, cookie_str in cookies_list:
        print(f"\n{'='*40}")
        print(f"正在签到: {name}")
        print('='*40)

        # 验证 Cookie 有效性
        from utils import validate_cookie
        is_valid, error_msg = validate_cookie(cookie_str)
        if not is_valid:
            print(f"[ERROR] Cookie 无效: {error_msg}")
            print(f"请更新 {name} 的 Cookie")
            all_success = False
            continue

        success = checkin(cookie_str)
        if success:
            # 签到成功后领取积分
            print("\n--- 领取签到积分 ---")
            claim_checkin_reward(cookie_str)

            # 领取VIP福利
            print("\n--- 领取VIP福利 ---")
            claim_vip_reward(cookie_str)
        else:
            all_success = False

    print(f"\n{'='*40}")
    if all_success:
        print("所有账号签到完成！")
    else:
        print("部分账号签到失败，请检查日志")

    return all_success


if __name__ == '__main__':
    success = main()
    exit(0 if success else 1)
